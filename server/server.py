import socket
import threading
import hashlib
import json
import time
import datetime
import psycopg2
from psycopg2 import sql
import os

HOST = '0.0.0.0'
PORT = 65432

DATABASE_URL = os.getenv('DATABASE_URL', 'dbname=chat_db user=chat_user password=chat_pass host=localhost port=5432')

clients = {} # {username: socket_object}
rooms = {}   # {room_name: {users: {username: socket_object}, history: [], stats: {total_messages: 0, active_users: 0}}}
lock = threading.Lock()

def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username, password):
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed."
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE username = %s", (username,))
        result = cursor.fetchone()
        conn.close()
        if result and result[0] == hash_password(password):
            return True, "Authentication successful."
        else:
            return False, "Invalid username or password."
    except Exception as e:
        print(f"Authentication error: {e}")
        return False, "Authentication error."

def register_user(username, password):
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed."
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id", (username, hash_password(password)))
        user_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return True, "Registration successful."
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        conn.close()
        return False, "Username already exists."
    except Exception as e:
        print(f"Registration error: {e}")
        conn.rollback()
        conn.close()
        return False, "Registration error."

def get_user_id(username):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        user_id = cursor.fetchone()
        conn.close()
        return user_id[0] if user_id else None
    except Exception as e:
        print(f"Error getting user ID: {e}")
        return None

def store_message(room_name, username, message_content):
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        user_id = get_user_id(username)
        cursor.execute("SELECT id FROM rooms WHERE name = %s", (room_name,))
        room_id = cursor.fetchone()[0]
        if user_id and room_id:
            cursor.execute("INSERT INTO messages (room_id, user_id, content) VALUES (%s, %s, %s)", (room_id, user_id, message_content))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error storing message: {e}")
        if conn:
            conn.rollback()
        if conn:
            conn.close()

def update_user_activity(user_id, room_id, message_count_increment=0, active_time_increment=0):
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_activity (user_id, room_id, messages_sent, active_time_seconds, last_activity)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (user_id, room_id) DO UPDATE SET
                messages_sent = user_activity.messages_sent + %s,
                active_time_seconds = user_activity.active_time_seconds + %s,
                last_activity = NOW()
        """, (user_id, room_id, message_count_increment, active_time_increment, message_count_increment, active_time_increment))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error updating user activity: {e}")
        if conn:
            conn.rollback()
        if conn:
            conn.close()

def get_room_history(room_name):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM rooms WHERE name = %s", (room_name,))
        room_id = cursor.fetchone()
        if not room_id:
            conn.close()
            return []
        room_id = room_id[0]
        cursor.execute("""
            SELECT u.username, m.content, m.timestamp
            FROM messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.room_id = %s
            ORDER BY m.timestamp ASC
            LIMIT 50
        """, (room_id,))
        history = [{"username": row[0], "message": row[1], "timestamp": str(row[2])} for row in cursor.fetchall()]
        conn.close()
        return history
    except Exception as e:
        print(f"Error getting room history: {e}")
        return []

def get_leaderboard():
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.username, SUM(ua.messages_sent) AS total_messages, SUM(ua.active_time_seconds) AS total_active_time
            FROM user_activity ua
            JOIN users u ON ua.user_id = u.id
            GROUP BY u.username
            ORDER BY total_messages DESC, total_active_time DESC
            LIMIT 10
        """)
        leaderboard = [{"username": row[0], "messages_sent": row[1], "active_time_seconds": row[2]} for row in cursor.fetchall()]
        conn.close()
        return leaderboard
    except Exception as e:
        print(f"Error getting leaderboard: {e}")
        return []

def broadcast_message(room_name, sender_username, message):
    with lock:
        if room_name in rooms:
            full_message = f"[{room_name}] {sender_username}: {message}"
            for client_socket in rooms[room_name]['users'].values():
                try:
                    client_socket.sendall(json.dumps({"type": "chat", "sender": sender_username, "room": room_name, "message": message}).encode('utf-8'))
                except:
                    pass # Client disconnected, will be handled by client_handler

def send_to_client(client_socket, data):
    try:
        client_socket.sendall(json.dumps(data).encode('utf-8'))
    except Exception as e:
        print(f"Error sending to client: {e}")

def create_room_db(room_name, is_private, owner_id):
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO rooms (name, is_private, owner_id) VALUES (%s, %s, %s)", (room_name, is_private, owner_id))
        conn.commit()
        conn.close()
        return True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        conn.close()
        return False
    except Exception as e:
        print(f"Error creating room in DB: {e}")
        conn.rollback()
        conn.close()
        return False

def get_all_rooms_db():
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name, is_private FROM rooms")
        rooms_data = [{"name": row[0], "is_private": row[1]} for row in cursor.fetchall()]
        conn.close()
        return rooms_data
    except Exception as e:
        print(f"Error getting all rooms from DB: {e}")
        return []

def client_handler(client_socket, addr):
    username = None
    current_room = None
    user_id = None
    last_activity_time = time.time()

    while True:
        try:
            message_data = client_socket.recv(4096).decode('utf-8')
            if not message_data:
                break

            request = json.loads(message_data)
            request_type = request.get("type")

            if request_type == "auth":
                username = request.get("username")
                password = request.get("password")
                success, msg = authenticate_user(username, password)
                if success:
                    user_id = get_user_id(username)
                    with lock:
                        clients[username] = client_socket
                    send_to_client(client_socket, {"type": "auth_response", "success": True, "message": msg, "username": username})
                    print(f"User {username} authenticated from {addr}")
                else:
                    send_to_client(client_socket, {"type": "auth_response", "success": False, "message": msg})
                    print(f"Authentication failed for {username} from {addr}: {msg}")
                    # client_socket.close() # Keep connection open for retry or register
                    # break # Close connection on failed auth

            elif request_type == "register":
                username = request.get("username")
                password = request.get("password")
                success, msg = register_user(username, password)
                if success:
                    send_to_client(client_socket, {"type": "register_response", "success": True, "message": msg})
                    print(f"User {username} registered from {addr}")
                else:
                    send_to_client(client_socket, {"type": "register_response", "success": False, "message": msg})
                    print(f"Registration failed for {username} from {addr}: {msg}")

            elif not username:
                send_to_client(client_socket, {"type": "error", "message": "Authentication required."})
                continue

            elif request_type == "create_room":
                room_name = request.get("room_name")
                is_private = request.get("is_private", False)
                owner_id = get_user_id(username)

                with lock:
                    if room_name in rooms:
                        send_to_client(client_socket, {"type": "room_creation_response", "success": False, "message": f"Room '{room_name}' already exists."})
                    else:
                        if create_room_db(room_name, is_private, owner_id):
                            rooms[room_name] = {'users': {}, 'history': [], 'stats': {'total_messages': 0, 'active_users': 0}}
                            send_to_client(client_socket, {"type": "room_creation_response", "success": True, "message": f"Room '{room_name}' created successfully."})
                            print(f"User {username} created room '{room_name}' (Private: {is_private})")
                        else:
                            send_to_client(client_socket, {"type": "room_creation_response", "success": False, "message": f"Failed to create room '{room_name}' in database."})

            elif request_type == "join_room":
                room_name = request.get("room_name")
                with lock:
                    if room_name in rooms:
                        if current_room:
                            rooms[current_room]['users'].pop(username, None)
                            rooms[current_room]['stats']['active_users'] = len(rooms[current_room]['users'])
                            broadcast_message(current_room, "SERVER", f"{username} has left the room.")

                        rooms[room_name]['users'][username] = client_socket
                        rooms[room_name]['stats']['active_users'] = len(rooms[room_name]['users'])
                        current_room = room_name
                        send_to_client(client_socket, {"type": "room_join_response", "success": True, "room": room_name, "message": f"Joined room '{room_name}'."})
                        broadcast_message(current_room, "SERVER", f"{username} has joined the room.")
                        history = get_room_history(room_name)
                        send_to_client(client_socket, {"type": "chat_history", "room": room_name, "history": history})
                        print(f"User {username} joined room '{room_name}'")
                    else:
                        send_to_client(client_socket, {"type": "room_join_response", "success": False, "message": f"Room '{room_name}' does not exist."})

            elif request_type == "leave_room":
                if current_room:
                    with lock:
                        if username in rooms[current_room]['users']:
                            rooms[current_room]['users'].pop(username)
                            rooms[current_room]['stats']['active_users'] = len(rooms[current_room]['users'])
                            broadcast_message(current_room, "SERVER", f"{username} has left the room.")
                            send_to_client(client_socket, {"type": "room_leave_response", "success": True, "room": current_room, "message": f"Left room '{current_room}'."})
                            print(f"User {username} left room '{current_room}'")
                            current_room = None
                        else:
                            send_to_client(client_socket, {"type": "room_leave_response", "success": False, "message": "You are not in this room."})
                else:
                    send_to_client(client_socket, {"type": "room_leave_response", "success": False, "message": "You are not currently in any room."})

            elif request_type == "message":
                message = request.get("message")
                if current_room and username:
                    broadcast_message(current_room, username, message)
                    store_message(current_room, username, message)
                    rooms[current_room]['stats']['total_messages'] += 1
                    update_user_activity(user_id, get_room_id(current_room), message_count_increment=1)
                    last_activity_time = time.time() # Reset activity time on message
                else:
                    send_to_client(client_socket, {"type": "error", "message": "You must join a room to send messages."})

            elif request_type == "list_rooms":
                room_list = get_all_rooms_db()
                send_to_client(client_socket, {"type": "room_list", "rooms": room_list})

            elif request_type == "room_info":
                if current_room:
                    with lock:
                        active_users_in_room = list(rooms[current_room]['users'].keys())
                        total_users_in_room = len(rooms[current_room]['users'])
                        total_messages_in_room = rooms[current_room]['stats']['total_messages']
                        send_to_client(client_socket, {
                            "type": "room_info",
                            "room_name": current_room,
                            "active_users": active_users_in_room,
                            "total_users_in_room": total_users_in_room,
                            "total_messages_in_room": total_messages_in_room
                        })
                else:
                    send_to_client(client_socket, {"type": "error", "message": "You are not in any room to view info."})

            elif request_type == "leaderboard":
                leaderboard_data = get_leaderboard()
                send_to_client(client_socket, {"type": "leaderboard_data", "leaderboard": leaderboard_data})

            else:
                send_to_client(client_socket, {"type": "error", "message": "Unknown command."})

            # Update active time for current user in current room
            if username and user_id and current_room:
                elapsed_time = int(time.time() - last_activity_time)
                if elapsed_time > 0:
                    update_user_activity(user_id, get_room_id(current_room), active_time_increment=elapsed_time)
                    last_activity_time = time.time()

        except json.JSONDecodeError:
            send_to_client(client_socket, {"type": "error", "message": "Invalid JSON format."})
        except ConnectionResetError:
            print(f"Client {username if username else addr} disconnected unexpectedly.")
            break
        except Exception as e:
            print(f"Error handling client {username if username else addr}: {e}")
            break

    # Cleanup on client disconnect
    with lock:
        if username and username in clients:
            del clients[username]
        if current_room and username in rooms[current_room]['users']:
            del rooms[current_room]['users'][username]
            rooms[current_room]['stats']['active_users'] = len(rooms[current_room]['users'])
            broadcast_message(current_room, "SERVER", f"{username} has disconnected.")
            print(f"User {username} disconnected from room '{current_room}'")
        print(f"Connection with {addr} closed.")
    client_socket.close()

def get_room_id(room_name):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM rooms WHERE name = %s", (room_name,))
        room_id = cursor.fetchone()
        conn.close()
        return room_id[0] if room_id else None
    except Exception as e:
        print(f"Error getting room ID: {e}")
        return None

def start_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(f"Server listening on {HOST}:{PORT}")

    # Load existing rooms from DB on startup
    db_rooms = get_all_rooms_db()
    for room_data in db_rooms:
        room_name = room_data['name']
        rooms[room_name] = {'users': {}, 'history': [], 'stats': {'total_messages': 0, 'active_users': 0}}
        print(f"Loaded room '{room_name}' from database.")

    while True:
        client_socket, addr = server_socket.accept()
        print(f"Accepted connection from {addr}")
        client_thread = threading.Thread(target=client_handler, args=(client_socket, addr))
        client_thread.start()

if __name__ == "__main__":
    start_server()

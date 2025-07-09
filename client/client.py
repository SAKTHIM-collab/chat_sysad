import socket
import threading
import json
import sys
import os

HOST = '127.0.0.1' # Connect to localhost for testing, will use server IP in Docker
PORT = 65432

class ChatClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = None
        self.username = None
        self.current_room = None
        self.stop_listening = threading.Event()
        self.listener_thread = None

    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            print(f"Connected to server at {self.host}:{self.port}")
            self.listener_thread = threading.Thread(target=self.listen_for_messages)
            self.listener_thread.daemon = True
            self.listener_thread.start()
            return True
        except ConnectionRefusedError:
            print("Connection refused. Make sure the server is running.")
            return False
        except Exception as e:
            print(f"Error connecting to server: {e}")
            return False

    def send_request(self, request_type, data={}):
        try:
            message = {"type": request_type, **data}
            self.socket.sendall(json.dumps(message).encode('utf-8'))
        except Exception as e:
            print(f"Error sending request: {e}")
            self.stop_listening.set() # Signal listener to stop on send error
            self.socket.close()
            sys.exit(1)

    def listen_for_messages(self):
        while not self.stop_listening.is_set():
            try:
                data = self.socket.recv(4096)
                if not data:
                    print("Server disconnected.")
                    self.stop_listening.set()
                    break
                response = json.loads(data.decode('utf-8'))
                self.handle_response(response)
            except ConnectionResetError:
                print("Server disconnected unexpectedly.")
                self.stop_listening.set()
                break
            except json.JSONDecodeError:
                print("Received malformed message from server.")
            except Exception as e:
                if not self.stop_listening.is_set(): # Only print error if not intentionally stopping
                    print(f"Error receiving message: {e}")
                self.stop_listening.set()
                break

    def handle_response(self, response):
        response_type = response.get("type")

        if response_type == "auth_response":
            if response["success"]:
                self.username = response["username"]
                print(f"Authentication successful. Welcome, {self.username}!")
                self.display_main_menu()
            else:
                print(f"Authentication failed: {response['message']}")
                self.display_auth_menu()

        elif response_type == "register_response":
            if response["success"]:
                print(f"Registration successful: {response['message']}")
                self.display_auth_menu()
            else:
                print(f"Registration failed: {response['message']}")

        elif response_type == "room_creation_response":
            if response["success"]:
                print(f"Room creation successful: {response['message']}")
            else:
                print(f"Room creation failed: {response['message']}")

        elif response_type == "room_join_response":
            if response["success"]:
                self.current_room = response["room"]
                print(f"Successfully joined room: {response['message']}")
                print(f"Type 'exit room' to leave, 'users' to see active users, 'history' for chat history, 'stats' for room stats, 'leaderboard' for overall stats.")
            else:
                print(f"Failed to join room: {response['message']}")

        elif response_type == "room_leave_response":
            if response["success"]:
                print(f"Successfully left room: {response['message']}")
                self.current_room = None
                self.display_main_menu()
            else:
                print(f"Failed to leave room: {response['message']}")

        elif response_type == "chat":
            sender = response.get("sender", "Unknown")
            room = response.get("room", "Unknown")
            message = response.get("message", "")
            print(f"\n[{room}] {sender}: {message}")
            if self.current_room:
                sys.stdout.write(f"[{self.current_room}]> ") # Re-prompt after message
            sys.stdout.flush()

        elif response_type == "chat_history":
            room_name = response.get("room")
            history = response.get("history", [])
            print(f"\n--- Chat History for {room_name} ---")
            if not history:
                print("No history available yet.")
            for msg in history:
                print(f"[{msg['timestamp']}] {msg['username']}: {msg['message']}")
            print("------------------------------")
            if self.current_room:
                sys.stdout.write(f"[{self.current_room}]> ")
            sys.stdout.flush()

        elif response_type == "room_list":
            rooms = response.get("rooms", [])
            print("\n--- Available Rooms ---")
            if not rooms:
                print("No rooms available. Create one!")
            else:
                for room in rooms:
                    status = "(Private)" if room['is_private'] else "(Public)"
                    print(f"- {room['name']} {status}")
            print("-----------------------")
            if self.username:
                self.display_main_menu()
            else:
                self.display_auth_menu()


        elif response_type == "room_info":
            room_name = response.get("room_name")
            active_users = response.get("active_users", [])
            total_users = response.get("total_users_in_room", 0)
            total_messages = response.get("total_messages_in_room", 0)
            print(f"\n--- Room Info for {room_name} ---")
            print(f"Active Users: {', '.join(active_users) if active_users else 'None'}")
            print(f"Total Current Users: {total_users}")
            print(f"Total Messages Sent in Room: {total_messages}")
            print("------------------------------")
            if self.current_room:
                sys.stdout.write(f"[{self.current_room}]> ")
            sys.stdout.flush()

        elif response_type == "leaderboard_data":
            leaderboard = response.get("leaderboard", [])
            print("\n--- Leaderboard (Top 10 Chatters) ---")
            if not leaderboard:
                print("No activity yet.")
            else:
                print(f"{'Username':<15} {'Messages':<10} {'Active Time (s)':<15}")
                print("-" * 40)
                for entry in leaderboard:
                    print(f"{entry['username']:<15} {entry['messages_sent']:<10} {entry['active_time_seconds']:<15}")
            print("-------------------------------------")
            if self.current_room:
                sys.stdout.write(f"[{self.current_room}]> ")
            elif self.username:
                self.display_main_menu()
            sys.stdout.flush()

        elif response_type == "error":
            print(f"Server error: {response['message']}")
            if self.current_room:
                sys.stdout.write(f"[{self.current_room}]> ")
            elif self.username:
                self.display_main_menu()
            else:
                self.display_auth_menu()
            sys.stdout.flush()

        else:
            print(f"Unknown response type: {response_type}")

    def display_auth_menu(self):
        print("\n--- Authentication ---")
        print("1. Login")
        print("2. Register")
        print("3. Exit")
        choice = input("Enter choice: ")
        if choice == '1':
            username = input("Username: ")
            password = input("Password: ")
            self.send_request("auth", {"username": username, "password": password})
        elif choice == '2':
            username = input("New Username: ")
            password = input("New Password: ")
            self.send_request("register", {"username": username, "password": password})
        elif choice == '3':
            self.shutdown()
        else:
            print("Invalid choice. Please try again.")
            self.display_auth_menu()

    def display_main_menu(self):
        print("\n--- Main Menu ---")
        print("1. List Rooms")
        print("2. Join Room")
        print("3. Create Room")
        print("4. Leaderboard")
        print("5. Logout")
        print("6. Exit")
        choice = input("Enter choice: ")
        if choice == '1':
            self.send_request("list_rooms")
        elif choice == '2':
            room_name = input("Enter room name to join: ")
            self.send_request("join_room", {"room_name": room_name})
        elif choice == '3':
            room_name = input("Enter new room name: ")
            is_private_str = input("Make room private? (yes/no): ").lower()
            is_private = True if is_private_str == 'yes' else False
            self.send_request("create_room", {"room_name": room_name, "is_private": is_private})
        elif choice == '4':
            self.send_request("leaderboard")
        elif choice == '5':
            print("Logging out...")
            self.username = None
            self.current_room = None
            self.display_auth_menu()
        elif choice == '6':
            self.shutdown()
        else:
            print("Invalid choice. Please try again.")
            self.display_main_menu()

    def chat_loop(self):
        while True:
            if self.current_room:
                try:
                    message = input(f"[{self.current_room}]> ")
                    if message.lower() == "exit room":
                        self.send_request("leave_room")
                    elif message.lower() == "users":
                        self.send_request("room_info")
                    elif message.lower() == "history":
                        self.send_request("chat_history", {"room_name": self.current_room})
                    elif message.lower() == "stats":
                        self.send_request("room_info")
                    elif message.lower() == "leaderboard":
                        self.send_request("leaderboard")
                    elif message:
                        self.send_request("message", {"room_name": self.current_room, "message": message})
                except EOFError: # Ctrl+D
                    print("Exiting chat due to EOF.")
                    self.shutdown()
                    break
                except KeyboardInterrupt: # Ctrl+C
                    print("\nExiting chat due to KeyboardInterrupt.")
                    self.shutdown()
                    break
            else:
                self.display_main_menu()
                # Need a way to break out of this loop if self.username becomes None
                while self.username and not self.current_room:
                    # Small sleep to prevent busy-waiting if menu input is fast
                    # Or, better, refactor input gathering to be blocking
                    time.sleep(0.1)

    def shutdown(self):
        print("Shutting down client.")
        self.stop_listening.set()
        if self.socket:
            self.socket.close()
        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=1)
        sys.exit(0)

if __name__ == "__main__":
    client = ChatClient(HOST, PORT)
    if client.connect():
        client.display_auth_menu()
        client.chat_loop()

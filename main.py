import asyncio
import json
from datetime import datetime
import requests
import websockets
import os
from websockets.exceptions import ConnectionClosed
PORT = int(os.environ.get("PORT", 10000))

connected_clients = {}         # user_id -> websocket
offline_messages = {}          # user_id -> list of messages

async def handle_connection(websocket):
    user_id = None
    user_name = None
    try:
        data = await websocket.recv()
        print("Initial connection data:", data)

        user = json.loads(data)
        user_id = user.get("id")
        user_role = user.get("role")

        if not user_id or not user_role:
            await websocket.send(json.dumps({"error": "Missing id or role"}))
            return

        user_name = f"{user_role.capitalize()}-{user_id}"
        connected_clients[user_id] = websocket
        print(f"{user_role} {user_name} connected.")
        print(f"Connected clients: {list(connected_clients.keys())}")

        # Send offline messages if any
        if user_id in offline_messages:
            for msg in offline_messages[user_id]:
                await websocket.send(json.dumps(msg))
            del offline_messages[user_id]

        while True:
            try:
                data = await websocket.recv()
                print("Received message:", data)

                msg_data = json.loads(data)
                msg_type = msg_data.get("type")

                if not msg_type:
                    await websocket.send(json.dumps({"error": "Missing message type"}))
                    continue

                if msg_type == "chat":
                    sender = msg_data.get("sender")
                    receiver = msg_data.get("to")
                    message_text = msg_data.get("message")

                    if not sender or not receiver or not message_text:
                        await websocket.send(json.dumps({"error": "Incomplete chat message"}))
                        continue

                    
                    if sender["role"] == "athlete" and receiver["role"] == "coach":
                        athlete_id = sender["id"]
                        coach_id = receiver["id"]
                    elif sender["role"] == "coach" and receiver["role"] == "athlete":
                        athlete_id = receiver["id"]
                        coach_id = sender["id"]
                    else:
                        await websocket.send(json.dumps({"error": "Invalid sender/receiver roles"}))
                        continue

                    try:
                        res = requests.post(
                            "https://sports-backend-oxiz.onrender.com/chat",
                            json={
                                "athlete_id": athlete_id,
                                "coach_id": coach_id,
                                "message": message_text
                            }
                        )
                        if res.status_code != 201:
                            print("Failed to save chat:", res.json())
                            await websocket.send(json.dumps({"error": "Failed to save chat message"}))
                            continue

                        chat_response = res.json()
                        timestamp = datetime.utcnow().isoformat()

                    except Exception as e:
                        print("Error while sending chat to backend:", e)
                        await websocket.send(json.dumps({"error": "Could not contact backend"}))
                        continue

                    response_payload = {
                        "type": "chat",
                        "from": sender,
                        "to": receiver,
                        "message": message_text,
                        "timestamp": timestamp
                    }

                    
                    recipient_ws = connected_clients.get(receiver["id"])
                    if recipient_ws:
                        await recipient_ws.send(json.dumps(response_payload))
                    else:
                        print(f"User {receiver['id']} is offline. Storing message.")
                        offline_messages.setdefault(receiver["id"], []).append(response_payload)

                elif msg_type == "typing":
                    sender = msg_data.get("sender")
                    receiver = msg_data.get("to")
                    if not sender or not receiver:
                        continue
                    recipient_ws = connected_clients.get(receiver["id"])
                    if recipient_ws:
                        await recipient_ws.send(json.dumps({
                            "type": "typing",
                            "from": sender
                        }))

                elif msg_type == "get_chat_list":
                    coach_id = msg_data.get("id")
                    try:
                        res = requests.get(f"https://sports-backend-oxiz.onrender.com/chat_list/{coach_id}")
                        if res.status_code == 200:
                            athletes = res.json().get("athletes", [])
                            await websocket.send(json.dumps({
                                "type": "chat_list",
                                "athletes": athletes
                            }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "chat_list",
                                "error": "Failed to fetch athlete list"
                            }))
                    except Exception as e:
                        print("Error fetching chat list:", e)
                        await websocket.send(json.dumps({
                            "type": "chat_list",
                            "error": "Server error"
                        }))

            except ConnectionClosed as e:
                print(f"Connection closed unexpectedly: {e.code} - {e.reason}")
                break
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"error": "Invalid JSON"}))
            except Exception as err:
                print("Error during message processing:", err)
                break

    except ConnectionClosed as e:
        print(f"{user_name or 'User'} disconnected: {e.code} - {e.reason}")
    except Exception as outer_exc:
        print("Outer connection error:", outer_exc)
    finally:
        if user_id and user_id in connected_clients:
            del connected_clients[user_id]
        print(f"Connected clients after disconnection: {list(connected_clients.keys())}")
        if not websocket.closed:
            await websocket.close()

async def main():
    async with websockets.serve(handle_connection, "0.0.0.0", PORT, ping_interval=30, ping_timeout=60):
        print(f"Running on ws://0.0.0.0:{PORT}")
    # async with websockets.serve(handle_connection, "localhost", 8775, ping_interval=30, ping_timeout=60):
        # print("WebSocket server running at ws://localhost:8775")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
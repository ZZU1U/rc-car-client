import cv2
import asyncio
import aiohttp
import json
import uuid
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCConfiguration, RTCIceServer
from aiortc.contrib.signaling import BYE
from av import VideoFrame
import time

JWT = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIwMTk2OGI0Yi01MTFjLTczMTMtYmY0YS01YWIzMGJkYzAzNGYiLCJ0b2tlbl90eXBlIjoiQ2FyIiwiZW1haWwiOm51bGwsImV4cCI6MTc0NjY5ODUxNSwiaXNfc3VwZXIiOm51bGwsImlhdCI6MTc0NjA5MzcxNX0.HBvVfvPcprWSiIbDMKkuWqYfhDeYF6sPLAZva0i_Kjw"

class CameraStreamTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.cap = cv2.VideoCapture(0)

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        ret, frame = self.cap.read()
        if not ret:
            raise Exception("Failed to read frame from camera")

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

async def run_offer(signaling_url: str, peer_id: str):

    # Send offer to signaling server
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(signaling_url) as ws:
            pc = None
            local_id = peer_id
            ices = []

            await ws.send_json({
                #"type": pc.localDescription.type,
                "uuid": local_id,
                "type": "register",
                "jwt": JWT,
                "role": "streamer",
            })

            async for msg in ws:
                #print(msg)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(msg.data)

                    if payload.get("type", "") == "error":
                        print(payload.get("msg", ""))

                    if payload.get("type", "") == "offer":
                        offer = RTCSessionDescription(
                            sdp=payload["sdp"],
                            type=payload["type"]
                        )

                        pc = RTCPeerConnection(RTCConfiguration(iceServers=[
                            RTCIceServer("stun:stun.l.google.com:19302"),
                            RTCIceServer("stun:stun1.l.google.com:19302")
                        ]))
                        pc.addTrack(CameraStreamTrack())  # This thing takes about a second

                        for ice in ices:
                            await pc.addIceCandidate(ice)

                        @pc.on("icecandidate")
                        async def on_icecandidate(candidate):
                            print(candidate)
                            if candidate:
                                # Send to signaling server
                                await ws.send_json({
                                    "uuid": local_id,
                                    "type": "ice-candidate",
                                    "candidate": candidate,
                                    "to": payload["uuid"]
                                })

                        @pc.on("datachannel")
                        def on_datachannel(channel):
                            print("Data channel created:", channel.label)

                            @channel.on("message")
                            def on_message(message):
                                print("Received from viewer:", message)
                                # Echo or process
                                if isinstance(message, str):
                                    try:
                                        data = json.loads(message)
                                        print("Parsed JSON:", data)
                                    except Exception:
                                        print("Received non-JSON message:", message)

                                # Optional: send a reply
                                channel.send(json.dumps({"hello": "from streamer"}))


                        await pc.setRemoteDescription(offer)
                        answer = await pc.createAnswer()
                        await pc.setLocalDescription(answer)

                        await ws.send_json({
                            "uuid": local_id,
                            "type": pc.localDescription.type,
                            "to": payload["uuid"],
                            "sdp": pc.localDescription.sdp
                        })
                    
                    if payload.get("type", "") == "ice":
                        if pc is None:
                            ices.append(payload["ice"])
                        else:
                            asyncio.ensure_future(pc.addIceCandidate(payload["ice"]))

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break

try:
    peer_id = "01968b4b-511c-7313-bf4a-5ab30bdc034f"
    print(f'Peer id is {peer_id}')
    signaling_url = "ws://gl.anohin.fvds.ru:8080/ws"
    asyncio.run(run_offer(signaling_url, peer_id))
except KeyboardInterrupt:
    print("Exiting...")


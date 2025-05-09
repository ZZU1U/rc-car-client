import cv2
import asyncio
import aiohttp
import json
import uuid
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCConfiguration, RTCIceServer
from aiortc.contrib.signaling import BYE
from av import VideoFrame
from dotenv import load_dotenv
import os
import sys
import time
import logging


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


class Streamer:
    def __init__(self):
        load_dotenv()
        self.uuid = os.environ.get('CAR_UUID')
        self.key= os.environ.get('CAR_KEY')

        self.server_url = os.environ.get('SERVER_URL')
        self.ws_url = os.environ.get('WS_URL')
        self.jwt = None

    async def get_jwt(self):
        async with aiohttp.ClientSession() as session:
            async with session.post(f'{self.server_url}/car/jwt', json={
                    'id': self.uuid, 'key': self.key    
                }) as response:

                response = await response.json()

                return response['access_token']

    async def run_offer(self):
        self.jwt = await self.get_jwt()
        print(self.jwt)
        # Send offer to signaling server
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f'{self.ws_url}/ws') as ws:
                pc = None
                ices = []

                await ws.send_json({
                    "uuid": self.uuid,
                    "type": "register",
                    "jwt": self.jwt,
                    "role": "streamer",
                })

                logging.info('Sent request for joining to signaling server')

                async for msg in ws:
                    logging.info(f'Received message {msg.type}')
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
                                        "uuid": self.uuid,
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
                                "uuid": self.uuid,
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

if __name__ == "__main__":
    logging.basicConfig(level='INFO')
    streamer = Streamer()
    asyncio.run(streamer.run_offer())



"""OBS set up for the demo takes (docs/video/CAPTURE-RUNBOOK.md), through its WebSocket server:
the scenes, each a window capture filling the 1920x1080 frame, the recording folder and quality.
Safe to run again: what exists is left as it is.

    .venv/Scripts/python scripts/obs_setup.py [--dir C:\\matterlift-video]

The WebSocket password is read from OBS's own config (or OBS_PW), never printed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import obsws_python as obs

# Window Capture "priority": 0 = match the title, 1 = the window class, 2 = the executable.
# "method" 2 = Windows Graphics Capture (Chrome, Godot and Blender draw with the GPU: BitBlt gives black).
WINDOWS = {
    "MatterLift (drawn cursor)": ("MatterLift:Chrome_WidgetWin_1:chrome.exe", 0, False),
    "MatterLift (real cursor)": ("MatterLift:Chrome_WidgetWin_1:chrome.exe", 0, True),
    "Explorer": ("matterlift-video:CabinetWClass:explorer.exe", 1, True),
    "Godot": (":Engine:Godot_v4.7.2-stable_win64.exe", 2, True),
    "Blender": (":GHOST_WindowClass:blender.exe", 2, True),
}
SCENES = {
    "APP_AUTO": ["MatterLift (drawn cursor)"],
    "APP": ["MatterLift (real cursor)"],
    "APP+MIC": ["MatterLift (real cursor)"],  # with the microphone unmuted for C08
    "EXPLORER": ["Explorer"],
    "GODOT": ["Godot"],
    "BLENDER": ["Blender"],
}


def password() -> str:
    if os.environ.get("OBS_PW"):
        return os.environ["OBS_PW"]
    cfg = Path(os.environ["APPDATA"]) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
    return json.loads(cfg.read_text(encoding="utf-8"))["server_password"]


def client() -> obs.ReqClient:
    return obs.ReqClient(host="localhost", port=4455, password=password(), timeout=10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="C:/matterlift-video")
    args = ap.parse_args()
    captures = Path(args.dir) / "captures"
    captures.mkdir(parents=True, exist_ok=True)

    c = client()
    video = c.get_video_settings()
    print(f"canvas {video.base_width}x{video.base_height}, output {video.output_width}x{video.output_height}, "
          f"{video.fps_numerator / video.fps_denominator:.0f} fps")
    scenes = {s["sceneName"] for s in c.get_scene_list().scenes}
    inputs = {i["inputName"] for i in c.get_input_list().inputs}

    for scene, sources in SCENES.items():
        if scene not in scenes:
            c.create_scene(scene)
            print("scene", scene)
        present = {i["sourceName"] for i in c.get_scene_item_list(scene).scene_items}
        for name in sources:
            window, priority, cursor = WINDOWS[name]
            settings = {"window": window, "priority": priority, "cursor": cursor, "client_area": True,
                        "method": 2, "compatibility": False}
            if name not in inputs:
                item = c.create_input(scene, name, "window_capture", settings, True).scene_item_id
                inputs.add(name)
            elif name not in present:
                item = c.create_scene_item(scene, name, True).scene_item_id
            else:
                continue
            # fill the frame whatever the window's size, keeping its proportions
            c.set_scene_item_transform(scene, item, {
                "boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsWidth": video.base_width,
                "boundsHeight": video.base_height, "boundsAlignment": 0, "positionX": 0, "positionY": 0,
                "alignment": 5})
            print(f"  {scene}: {name} ({'cursor' if cursor else 'no cursor'})")

    # sound: off by default (the takes are silent; C08 unmutes the mic itself)
    for i in c.get_input_list().inputs:
        if i["inputKind"] in ("wasapi_output_capture", "wasapi_input_capture"):
            c.set_input_mute(i["inputName"], True)

    c.set_record_directory(str(captures))
    c.set_profile_parameter("SimpleOutput", "FilePath", str(captures))
    c.set_profile_parameter("SimpleOutput", "RecQuality", "HQ")  # "indistinguishable quality"
    c.set_current_program_scene("APP_AUTO")
    print("recording to", c.get_record_directory().record_directory)


if __name__ == "__main__":
    main()

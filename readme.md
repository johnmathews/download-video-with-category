# About

This project will very simply use yt-dlp to download a video of the highest
possible audio and video quality.
The script will be run from the command line and the youtube share url will be provided.

e.g `yt https://youtu.be/u6LztryAUUA?si=-6VFb1454VSt-R2Z`

the video file will be saved into ~/Desktop/videos

youtube subtitles are also downloaded (auto generated and normal, in english and dutch)
video thumbnail and metadata are also downloaded.

`uv` is used to manage python virtual envs, scripts and dependencies.

a shell wrapper is used so that the script can be invoked from a zsh terminal session, even though the script itself is written in python.

the most recent LTS version of python is used.

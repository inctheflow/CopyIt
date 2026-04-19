#!/bin/bash
cd ~/Desktop/CopyIt
source venv/bin/activate
nohup python3 copyit.py > /tmp/copyit.log 2>&1 &

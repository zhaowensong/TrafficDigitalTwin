#!/bin/bash
cd /mnt/Data/visitor/TrafficDigitalTwin
source venv/bin/activate
python3 -c "
import torch
print('PyTorch:', torch.__version__)
print('CUDA:', torch.cuda.is_available())
print('GPUs:', torch.cuda.device_count())
if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        print(f'  GPU {i}: {torch.cuda.get_device_name(i)}')
"

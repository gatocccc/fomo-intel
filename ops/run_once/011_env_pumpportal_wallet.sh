#!/bin/bash
cd /root/fomo_intel; grep -q "^PUMPPORTAL_WALLET=" .env || echo "PUMPPORTAL_WALLET=FYxmJNnNs9fo9NhBX1GjbMNXF96KETTYCwxKXoFTcXan" >> .env; systemctl restart fomo-live; sleep 3; systemctl is-active fomo-live

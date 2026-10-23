#!/bin/bash
# Carga la API key de PumpPortal en el .env del servidor y reinicia el bot.
cd /root/fomo_intel
KEY="en4jyvve8tx44mb4dxvm8htt8dp74hkc8djkjna865gmmwb6edrmmnvtb5j6uktqa99men3r6n33cvvp61hm6nvf99mmmbvh61mpmwarat66ggtp69v6pjap6nnmrwvu6nppyv37a4ykua9gpcvj16da7av1redjpprhgcwewvq2tage1v5guu88hp48avg9tn52g9nctkkuf8"
grep -v '^PUMPPORTAL_API_KEY=' .env > .env.new; echo "PUMPPORTAL_API_KEY=$KEY" >> .env.new; cat .env.new > .env; rm -f .env.new; chmod 600 .env
systemctl restart fomo-live; sleep 4; systemctl is-active fomo-live
journalctl -u fomo-live --no-pager -n 5

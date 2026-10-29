"""Billetera de laboratorio (29/10/2026, pedido de Gastón): capital separado para probar hipótesis nuevas en real, con tamaño chico,
antes de que toquen el libro. Se fondea con ~10% del libro: el libro vende USDC por SOL (decisión lloyd-2026-10-29-01) y este script
transfiere el SOL a secrets/plan_lab.json, baja el inicio del libro en lo transferido (para no mostrar una pérdida falsa) y anota todo.

Uso (servidor): python -m fomo_intel.desk.fund_lab SOL_A_TRANSFERIR
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

from ..live.config import Env
from ..live.wallet import Rpc, load_or_create


def main():
    from ..live.bot import load_dotenv
    load_dotenv()
    from solders.hash import Hash
    from solders.instruction import Instruction
    from solders.pubkey import Pubkey
    from solders.system_program import TransferParams, transfer
    from solders.transaction import Transaction
    amt = float(sys.argv[1])
    rpc = Rpc(Env().rpc_url)
    src = load_or_create(Path("secrets/plan_lloyd.json")); lab = load_or_create(Path("secrets/plan_lab.json"))
    print("libro", src.pubkey(), "SOL", rpc.sol_balance(str(src.pubkey())), "| lab", lab.pubkey())
    for _ in range(40):                       # esperar a que la venta de USDC del libro deje el SOL
        if rpc.sol_balance(str(src.pubkey())) >= amt + 0.04:
            break
        time.sleep(10)
    bal = rpc.sol_balance(str(src.pubkey()))
    if bal < amt + 0.04:
        print("SOL insuficiente en el libro:", bal); return
    CB = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
    ixs = [Instruction(CB, bytes([2]) + (60_000).to_bytes(4, "little"), []), Instruction(CB, bytes([3]) + (300_000).to_bytes(8, "little"), []),
           transfer(TransferParams(from_pubkey=src.pubkey(), to_pubkey=lab.pubkey(), lamports=int(amt * 1e9)))]
    sig = None
    for i in range(3):
        bh = rpc.call("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
        tx = Transaction.new_signed_with_payer(ixs, src.pubkey(), [src], Hash.from_string(bh))
        sig = rpc.send_raw(base64.b64encode(bytes(tx)).decode())
        if rpc.wait_confirmed(sig, 75):
            break
        sig = None
    if not sig:
        print("transferencia sin confirmar"); return
    print("transferido", amt, "SOL:", sig)
    sol_usd = json.load(open("state/plan_lloyd_summary.json")).get("sol_usd") or 100
    usd = round(amt * sol_usd, 2)
    cfg_p = Path("state/plan_lloyd/config.json"); cfg = json.load(open(cfg_p))
    cfg["start_usd"] = round(cfg["start_usd"] - usd, 2); cfg["start_sol"] = round(cfg.get("start_sol", 0) - amt, 4)
    cfg["floor_usd"] = round(cfg["start_usd"] * 0.4, 2); cfg.setdefault("transfers", []).append({"ts": time.time(), "to": "lab", "sol": amt, "usd": usd, "sig": sig})
    json.dump(cfg, open(cfg_p, "w"), indent=1)
    with open("state/plan_lloyd/journal.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "title": "A tenth of the book moves to the lab", "kind": "system",
                            "text": f"{amt} SOL (${usd}) moved to Lloyd's lab wallet ({lab.pubkey()}), where new ideas are tested live with small size before they "
                                    f"touch the main book. The book's starting balance was lowered by the same amount, so this is not shown as a loss."}, ensure_ascii=False) + "\n")
    print("inicio del libro ahora", cfg["start_usd"])


if __name__ == "__main__":
    main()

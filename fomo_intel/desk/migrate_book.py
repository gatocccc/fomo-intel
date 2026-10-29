"""Migración a un solo libro (28/10/2026 noche): los tres planes (agresivo, equilibrado, tradicional) pasan a UNA billetera, "lloyd".

- La billetera del plan agresivo pasa a ser la del libro (se copia su clave a secrets/plan_lloyd.json).
- De equilibrado y tradicional se transfieren todos los tokens SPL (USDC, STONK, USELESS, SPX…) y el SOL (menos 0,003 para rent) a lloyd.
- state/plan_lloyd/ nace con las posiciones de los tres (con su bolsillo: picks / established / cash), los cierres, operaciones y
  diario de los tres (ordenados por fecha), y start_usd = suma de los tres arranques.
- Nunca vende nada: solo mueve lo que hay. Idempotente: si lloyd ya existe, no toca.

Uso (en el servidor): python -m fomo_intel.desk.migrate_book [--dry]
"""
from __future__ import annotations

import base64
import json
import shutil
import sys
import time
from pathlib import Path

from ..live.config import Env
from ..live.wallet import Rpc, load_or_create

TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN22 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA_PROG = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SLEEVE = {USDC: "cash", "4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz": "picks"}
SOURCES = ("equilibrado", "tradicional")
SOL_KEEP = 0.003


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def token_accounts(rpc: Rpc, owner: str):
    out = []
    for prog in (TOKEN, TOKEN22):
        r = rpc.call("getTokenAccountsByOwner", [owner, {"programId": prog}, {"encoding": "jsonParsed"}]) or {}
        for a in r.get("value", []):
            info = a["account"]["data"]["parsed"]["info"]
            amt = int(info["tokenAmount"]["amount"])
            if amt > 0:
                out.append({"pubkey": a["pubkey"], "mint": info["mint"], "amount": amt, "decimals": info["tokenAmount"]["decimals"], "program": prog})
    return out


def ata(owner, mint, prog):
    from solders.pubkey import Pubkey
    return Pubkey.find_program_address([bytes(Pubkey.from_string(owner)), bytes(Pubkey.from_string(prog)), bytes(Pubkey.from_string(mint))],
                                       Pubkey.from_string(ATA_PROG))[0]


def transfer_all(rpc: Rpc, kp, dest: str, dry: bool):
    """Mueve todos los tokens y el SOL (menos SOL_KEEP) de kp a dest. Devuelve lista de (qué, cuánto, firma)."""
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.system_program import TransferParams, transfer
    from solders.transaction import Transaction

    src = str(kp.pubkey()); done = []
    for t in token_accounts(rpc, src):
        mint, prog = t["mint"], t["program"]
        dest_ata = ata(dest, mint, prog)
        ixs = [Instruction(Pubkey.from_string(ATA_PROG),
                           bytes([1]),   # create idempotent
                           [AccountMeta(kp.pubkey(), True, True), AccountMeta(dest_ata, False, True), AccountMeta(Pubkey.from_string(dest), False, False),
                            AccountMeta(Pubkey.from_string(mint), False, False), AccountMeta(Pubkey.from_string("11111111111111111111111111111111"), False, False),
                            AccountMeta(Pubkey.from_string(prog), False, False)]),
               Instruction(Pubkey.from_string(prog),
                           bytes([12]) + t["amount"].to_bytes(8, "little") + bytes([t["decimals"]]),   # TransferChecked
                           [AccountMeta(Pubkey.from_string(t["pubkey"]), False, True), AccountMeta(Pubkey.from_string(mint), False, False),
                            AccountMeta(dest_ata, False, True), AccountMeta(kp.pubkey(), True, False)])]
        if dry:
            log(f"  [dry] {src[:6]} → {dest[:6]}: {t['amount'] / 10 ** t['decimals']:.6g} de {mint[:8]}"); continue
        bh = rpc.call("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
        tx = Transaction.new_signed_with_payer(ixs, kp.pubkey(), [kp], Hash.from_string(bh))
        sig = rpc.send_raw(base64.b64encode(bytes(tx)).decode())
        st = rpc.wait_confirmed(sig, 150)
        log(f"  tokens {mint[:8]} {t['amount'] / 10 ** t['decimals']:.6g}: {sig[:16]}… {'ok' if st else 'SIN CONFIRMAR'}")
        done.append((mint, t["amount"] / 10 ** t["decimals"], sig, bool(st)))
        time.sleep(2)
    bal = rpc.sol_balance(src)
    lam = int((bal - SOL_KEEP) * 1e9) - 5000
    if lam > 0:
        if dry:
            log(f"  [dry] SOL {lam / 1e9:.6f}")
        else:
            bh = rpc.call("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
            ix = transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=Pubkey.from_string(dest), lamports=lam))
            tx = Transaction.new_signed_with_payer([ix], kp.pubkey(), [kp], Hash.from_string(bh))
            sig = rpc.send_raw(base64.b64encode(bytes(tx)).decode()); st = rpc.wait_confirmed(sig, 90)
            log(f"  SOL {lam / 1e9:.6f}: {sig[:16]}… {'ok' if st else 'SIN CONFIRMAR'}")
            done.append(("SOL", lam / 1e9, sig, bool(st)))
    return done


def jl(p, d=None):
    try: return json.load(open(p))
    except Exception: return d  # noqa: BLE001


def lines(p):
    out = []
    if Path(p).exists():
        for l in Path(p).read_text().splitlines():
            try: out.append(json.loads(l))
            except Exception: pass  # noqa: BLE001
    return out


def main():
    dry = "--dry" in sys.argv
    from ..live.bot import load_dotenv
    load_dotenv()
    env = Env(); rpc = Rpc(env.rpc_url)
    dst_dir = Path("state/plan_lloyd")
    if "--transfer-only" in sys.argv:          # reintento: mover lo que haya quedado en las billeteras viejas (sin tocar el estado)
        lloyd_pub = json.load(open("secrets/plan_lloyd.json"))["pubkey"]
        for src in SOURCES:
            kp = load_or_create(Path(f"secrets/plan_{src}.json"))
            log(f"reintento {src} ({kp.pubkey()}) → lloyd"); transfer_all(rpc, kp, lloyd_pub, dry)
        return
    if dst_dir.exists() and (dst_dir / "config.json").exists() and not dry:
        log("state/plan_lloyd ya existe: no se migra dos veces"); return
    if not dry:
        Path("secrets/plan_lloyd.json").exists() or shutil.copy("secrets/plan_agresivo.json", "secrets/plan_lloyd.json")
    lloyd_pub = json.load(open("secrets/plan_agresivo.json"))["pubkey"]
    log("libro lloyd =", lloyd_pub)
    # 1) mover fondos
    moved = {}
    for src in SOURCES:
        kp = load_or_create(Path(f"secrets/plan_{src}.json"))
        log(f"moviendo {src} ({kp.pubkey()}) → lloyd")
        moved[src] = transfer_all(rpc, kp, lloyd_pub, dry)
    # 2) estado del libro = unión de los tres
    plans = ["agresivo"] + list(SOURCES)
    pos, closed, trades, journal, equity = {}, [], [], [], []
    start_usd = start_sol = 0.0; start_ts = None
    for p in plans:
        d = Path(f"state/plan_{p}")
        cfg = jl(d / "config.json", {})
        if cfg.get("start_ts"):
            start_usd += cfg.get("start_usd") or 0; start_sol += cfg.get("start_sol") or 0
            start_ts = min(start_ts or cfg["start_ts"], cfg["start_ts"])
        for m, x in (jl(d / "positions.json", {}) or {}).items():
            x = dict(x); x["sleeve"] = SLEEVE.get(m, "established" if p == "equilibrado" else "picks"); x["from_plan"] = p
            if m in pos:   # misma mint en dos planes (p. ej. USDC): se suman
                a = pos[m]; tot = a["tokens"] + x["tokens"]
                a["entry_usd"] = (a["entry_usd"] * a["tokens"] + x["entry_usd"] * x["tokens"]) / tot if tot else a["entry_usd"]
                a["tokens"] = tot; a["tokens_initial"] += x["tokens_initial"]; a["sol_in"] += x["sol_in"]; a["sol_out"] += x["sol_out"]
            else:
                pos[m] = x
        for r in lines(d / "closed.jsonl"): r["from_plan"] = p; closed.append(r)
        for r in lines(d / "trades.jsonl"): r["from_plan"] = p; trades.append(r)
        for r in lines(d / "journal.jsonl"): r["from_plan"] = p; journal.append(r)
        if p == "agresivo":
            equity = lines(d / "equity.jsonl")
    for lst in (closed, trades, journal):
        lst.sort(key=lambda r: r.get("ts", 0))
    log(f"posiciones {list(pos)}; cierres {len(closed)}; operaciones {len(trades)}; diario {len(journal)}; start_usd {start_usd:.2f}")
    if dry:
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    json.dump(pos, open(dst_dir / "positions.json", "w"), indent=1)
    for name, lst in (("closed.jsonl", closed), ("trades.jsonl", trades), ("journal.jsonl", journal), ("equity.jsonl", equity)):
        with open(dst_dir / name, "w") as f:
            for r in lst: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    processed = []
    for p in plans:
        processed += jl(Path(f"state/plan_{p}/processed.json"), [])
    json.dump(processed, open(dst_dir / "processed.json", "w"))
    sol_usd = jl("state/plan_agresivo_summary.json", {}).get("sol_usd") or 100
    cfg = {"start_ts": start_ts, "start_usd": round(start_usd, 2), "start_sol": round(start_sol, 4), "goal_mult": 2, "days": 365,
           "floor_usd": round(start_usd * 0.4, 2), "reserve_sol": 0.03, "max_slippage_pct": 8.0, "swap_slippage_pct": 12.0,
           "priority_fee_sol": 0.001, "plan": "lloyd", "migrated_ts": time.time(), "migrated_from": plans}
    json.dump(cfg, open(dst_dir / "config.json", "w"), indent=1)
    with open(dst_dir / "journal.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "title": "One book from here on", "kind": "system",
                            "text": "The three house plans (Aggressive, Balanced, Core) were merged into a single book tonight. Everything they held moved into this wallet, "
                                    "with the same stops: GTA6 in the Picks pocket; STONK, USELESS and SPX in Established memes; USDC in Cash. Their closed trades and notes "
                                    "are kept above. From now on Lloyd decides how much goes to each pocket according to the market, instead of three fixed plans. "
                                    f"Starting balance of the book: ${start_usd:.2f} (the sum of the three plans' starts)."}, ensure_ascii=False) + "\n")
    json.dump({"ts": time.time(), "moved": moved}, open(dst_dir / "migration.json", "w"), indent=1, default=str)
    log("listo. Ahora: systemctl disable --now fomo-desk@agresivo fomo-desk@equilibrado fomo-desk@tradicional; systemctl enable --now fomo-desk@lloyd")


if __name__ == "__main__":
    main()

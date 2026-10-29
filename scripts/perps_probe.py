"""Sonda de Jupiter Perpetuals para correr en el servidor (la sandbox no llega a perps-api.jup.ag).

Uso:
  python -m scripts.perps_probe spec                       # baja /v1/docs, extrae el OpenAPI y lo resume
  python -m scripts.perps_probe positions
  python -m scripts.perps_probe price SOL
  python -m scripts.perps_probe quote SOL short 10 2       # símbolo lado colateral_usdc apalancamiento
  python -m scripts.perps_probe open  SOL short 10 2 --dry   (default) | --live
  python -m scripts.perps_probe close <positionPubkey> --dry | --live

Opciones globales: --wallet PATH (default secrets/plan_lloyd.json), --rpc URL (default env SOLANA_RPC_URL),
--env PATH (default .env), -v para logs DEBUG. Imprime JSON compacto.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

import requests

from fomo_intel.live.bot import load_dotenv
from fomo_intel.live.perps import BASE_URL, USDC, JupPerps, PerpsApiError, PerpsError
from fomo_intel.live.wallet import Rpc, load_or_create

DOCS_URL = f"{BASE_URL}/docs"
SPEC_OUT = Path("state/ops/perps_openapi.json")
INTEREST = ("/positions/increase", "/positions/decrease", "/positions-gasless/decrease")


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str))


def _slim(res: dict) -> dict:
    """Saca el `raw` de las posiciones para que la salida sea compacta."""
    if isinstance(res, list):
        return [_slim(x) for x in res]
    if isinstance(res, dict):
        return {k: _slim(v) for k, v in res.items() if k != "raw"}
    return res


# ----------------------------------------------------------------- spec
def _extract_redoc_state(html: str) -> dict:
    """Encuentra `const __redoc_state = {...}` y lo decodifica con raw_decode (ignora el `;` y lo que siga)."""
    m = re.search(r"__redoc_state\s*=\s*", html)
    if not m:
        raise RuntimeError("no __redoc_state in docs HTML")
    start = html.index("{", m.end())
    obj, _ = json.JSONDecoder().raw_decode(html[start:])
    return obj


def _spec_from_state(state: dict) -> dict:
    spec = (state.get("spec") or {}).get("data") if isinstance(state.get("spec"), dict) else state.get("spec")
    if spec is None:
        spec = state.get("data") or state
    if isinstance(spec, str):          # a veces viene como JSON serializado dentro del JSON
        spec = json.loads(spec)
    if isinstance(spec, str):          # ...y a veces doblemente
        spec = json.loads(spec)
    if not isinstance(spec, dict) or "paths" not in spec:
        raise RuntimeError(f"unexpected spec shape: keys={list(spec)[:10] if isinstance(spec, dict) else type(spec)}")
    return spec


def _resolve(spec: dict, node, depth: int = 0, seen: tuple = ()) -> object:
    """Expande $ref recursivamente (con tope de profundidad y guardia de ciclos) y conserva enums."""
    if depth > 12:
        return "<depth>"
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"]
            if ref in seen:
                return f"<recursive {ref}>"
            target = spec
            for part in ref.lstrip("#/").split("/"):
                target = (target or {}).get(part.replace("~1", "/").replace("~0", "~"))
            if target is None:
                return f"<unresolved {ref}>"
            return _resolve(spec, target, depth + 1, seen + (ref,))
        return {k: _resolve(spec, v, depth + 1, seen) for k, v in node.items()
                if k not in ("example", "examples", "x-codeSamples")}
    if isinstance(node, list):
        return [_resolve(spec, x, depth + 1, seen) for x in node]
    return node


def _schema_summary(schema, indent: int = 0, lines: list[str] | None = None, name: str = "") -> list[str]:
    """Resumen legible: campo: tipo [required] [enum=...]."""
    lines = [] if lines is None else lines
    pad = "  " * indent
    if not isinstance(schema, dict):
        lines.append(f"{pad}{name}: {schema}")
        return lines
    t = schema.get("type") or ("object" if "properties" in schema else "")
    enum = schema.get("enum")
    head = f"{pad}{name}: {t}" if name else f"{pad}{t}"
    if enum:
        head += f" enum={enum}"
    if schema.get("nullable"):
        head += " nullable"
    if schema.get("description"):
        head += f"  -- {str(schema['description'])[:120]}"
    for comb in ("oneOf", "anyOf", "allOf"):
        if comb in schema:
            lines.append(head + f" {comb}:")
            for alt in schema[comb]:
                _schema_summary(alt, indent + 1, lines, "-")
            return lines
    lines.append(head)
    req = set(schema.get("required") or [])
    for k, v in (schema.get("properties") or {}).items():
        _schema_summary(v, indent + 1, lines, f"{k}{'*' if k in req else ''}")
    if "items" in schema:
        _schema_summary(schema["items"], indent + 1, lines, "[items]")
    return lines


def cmd_spec(_a) -> int:
    r = requests.get(DOCS_URL, timeout=30, headers={"user-agent": "fomo-intel-perps/0.1"})
    print(f"GET {DOCS_URL} -> {r.status_code} ({len(r.content)} bytes)")
    r.raise_for_status()
    SPEC_OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        spec = _spec_from_state(_extract_redoc_state(r.text))
    except Exception as e:  # noqa: BLE001
        html_out = SPEC_OUT.with_suffix(".html")
        html_out.write_text(r.text)
        print(f"could not extract spec: {e}; raw HTML saved to {html_out}")
        # último recurso: ¿hay un link a un JSON de spec en el HTML?
        for link in re.findall(r"""['"]([^'"]+\.(?:json|yaml))['"]""", r.text)[:10]:
            print("  candidate spec link:", link)
        return 1
    SPEC_OUT.write_text(json.dumps(spec, indent=1))
    print(f"spec saved to {SPEC_OUT} (openapi {spec.get('openapi') or spec.get('swagger')}, title={spec.get('info', {}).get('title')})")

    print("\n== paths ==")
    for path, item in sorted(spec["paths"].items()):
        for method, op in item.items():
            if method.lower() in ("get", "post", "put", "patch", "delete"):
                print(f"  {method.upper():6} {path}   {op.get('summary') or op.get('operationId') or ''}")

    for path in INTEREST:
        item = spec["paths"].get(path)
        if not item:
            print(f"\n== {path}: NOT IN SPEC ==")
            continue
        for method, op in item.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            print(f"\n== {method.upper()} {path} ==")
            rb = _resolve(spec, op.get("requestBody") or {})
            for ctype, media in (rb.get("content") or {}).items():
                print(f"  request ({ctype}):")
                for ln in _schema_summary(media.get("schema") or {}, 2):
                    print(ln)
            for code, resp in (op.get("responses") or {}).items():
                resp = _resolve(spec, resp)
                for ctype, media in (resp.get("content") or {}).items():
                    print(f"  response {code} ({ctype}):")
                    for ln in _schema_summary(media.get("schema") or {}, 2):
                        print(ln)
            # parámetros de query/path, por si los hay
            for prm in _resolve(spec, op.get("parameters") or []):
                print(f"  param {prm.get('in')}: {prm.get('name')}{'*' if prm.get('required') else ''} {json.dumps(prm.get('schema'))}")
    return 0


# ------------------------------------------------------------- comandos
def _client(a) -> JupPerps:
    load_dotenv(a.env)
    rpc_url = a.rpc or os.getenv("SOLANA_RPC_URL")
    if not rpc_url:
        key = os.getenv("HELIUS_API_KEY")
        if not key:
            sys.exit("no RPC: set SOLANA_RPC_URL (or HELIUS_API_KEY) in .env or pass --rpc")
        rpc_url = f"https://mainnet.helius-rpc.com/?api-key={key}"
    wallet = Path(a.wallet)
    if not wallet.exists():
        sys.exit(f"wallet file not found: {wallet}")
    kp = load_or_create(wallet)
    log = logging.getLogger("perps")
    log.info("wallet %s rpc %s", kp.pubkey(), rpc_url.split("?")[0])
    return JupPerps(kp, Rpc(rpc_url), log=log)


def cmd_positions(a) -> int:
    c = _client(a)
    pos = c.positions()
    _out({"wallet": c.wallet, "count": len(pos), "positions": _slim(pos) if not a.raw else pos})
    return 0


def cmd_price(a) -> int:
    c = _client(a)
    _out({"symbol": a.symbol.upper(), "price": c.price(a.symbol), "stats": c.market_stats(a.symbol)})
    return 0


def cmd_quote(a) -> int:
    c = _client(a)
    q = c.quote_open(a.symbol, a.side, a.collateral, a.leverage, a.slippage)
    _out(q if a.raw else _slim(q))
    return 0


def cmd_open(a) -> int:
    c = _client(a)
    dry = not a.live
    if not dry:
        print(f"LIVE: opening {a.side} {a.symbol.upper()} collateral {a.collateral} USDC x{a.leverage} from {c.wallet}", file=sys.stderr)
    res = c.open(a.symbol, a.side, a.collateral, a.leverage, a.slippage, dry=dry)
    _out(res)
    return 0 if res.get("ok") else 2


def cmd_close(a) -> int:
    c = _client(a)
    dry = not a.live
    if not dry:
        print(f"LIVE: closing {a.pubkey} -> {a.mint}", file=sys.stderr)
    res = c.close(a.pubkey, a.mint, dry=dry)
    _out(res)
    return 0 if res.get("ok") else 2


def main(argv=None) -> int:
    def common(p, suppress: bool):
        # las opciones globales se aceptan antes o después del subcomando; las del subcomando pisan a las globales
        d = argparse.SUPPRESS if suppress else None
        p.add_argument("--wallet", default=d if suppress else "secrets/plan_lloyd.json")
        p.add_argument("--rpc", default=d)
        p.add_argument("--env", default=d if suppress else ".env")
        p.add_argument("--raw", action="store_true", default=d if suppress else False, help="incluir las respuestas crudas de la API")
        p.add_argument("-v", action="store_true", default=d if suppress else False, help="logs DEBUG")

    ap = argparse.ArgumentParser(prog="perps_probe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common(ap, suppress=False)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name):
        p = sub.add_parser(name); common(p, suppress=True); return p

    add("spec").set_defaults(fn=cmd_spec)
    add("positions").set_defaults(fn=cmd_positions)
    p = add("price"); p.add_argument("symbol"); p.set_defaults(fn=cmd_price)

    def trade_args(p):
        p.add_argument("symbol"); p.add_argument("side", choices=["long", "short"])
        p.add_argument("collateral", type=float, help="USDC"); p.add_argument("leverage", type=float)
        p.add_argument("--slippage", type=int, default=100, help="bps")

    p = add("quote"); trade_args(p); p.set_defaults(fn=cmd_quote)
    p = add("open"); trade_args(p)
    g = p.add_mutually_exclusive_group(); g.add_argument("--dry", action="store_true"); g.add_argument("--live", action="store_true")
    p.set_defaults(fn=cmd_open)
    p = add("close"); p.add_argument("pubkey"); p.add_argument("--mint", default=USDC)
    g = p.add_mutually_exclusive_group(); g.add_argument("--dry", action="store_true"); g.add_argument("--live", action="store_true")
    p.set_defaults(fn=cmd_close)

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stderr)
    try:
        return a.fn(a)
    except PerpsApiError as e:
        _out({"ok": False, "error": f"HTTP {e.status} {e.path}", "body": e.body[:2000]})
        return 3
    except PerpsError as e:
        _out({"ok": False, "error": str(e)})
        return 3


if __name__ == "__main__":
    sys.exit(main())

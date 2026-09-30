"""Latest EUR->USD reference rate from the public Frankfurter API.

FX_API_KEY comes from the node's continuo-api-demo-fx Secret. Frankfurter
needs no key, so the script only checks it arrived and never sends or logs it.
"""
import json
import logging
import os
import urllib.request
from datetime import date

import pyarrow as pa

logger = logging.getLogger(__name__)

URL = "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD"


def run(ctx):
    if not os.environ.get("FX_API_KEY"):
        raise RuntimeError("FX_API_KEY is not set; is Secret continuo-api-demo-fx present?")
    logger.info("credential present")
    # Frankfurter's edge rejects urllib's default User-Agent with a 403.
    req = urllib.request.Request(URL, headers={"User-Agent": "continuo-demo-fx/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    return pa.table(
        {
            "rate_date": pa.array([date.fromisoformat(body["date"])], type=pa.date32()),
            "base": pa.array([body["base"]], type=pa.string()),
            "quote": pa.array(["USD"], type=pa.string()),
            "rate": pa.array([float(body["rates"]["USD"])], type=pa.float64()),
        }
    )

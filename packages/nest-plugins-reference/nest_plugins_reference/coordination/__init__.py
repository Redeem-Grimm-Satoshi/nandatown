# SPDX-License-Identifier: Apache-2.0
"""Coordination layer reference plugins.

Two reference implementations live here:

* :mod:`contract_net` — minimal FIPA Contract Net scaffold (default).
* :mod:`sealed_bid` — sealed-bid auction with first-price and Vickrey
  (second-price) variants, reserve prices, FIPA-style state tracking,
  and a companion :mod:`validators` module that checks
  mechanism-design invariants on resolved rounds.
"""

from nest_plugins_reference.coordination.contract_net import ContractNet
from nest_plugins_reference.coordination.sealed_bid import (
    SealedBidAuction,
    SealedBidAuctionError,
)

__all__ = [
    "ContractNet",
    "SealedBidAuction",
    "SealedBidAuctionError",
]

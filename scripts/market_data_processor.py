#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# market_data_processor.py
# Legacy Market Data Processing Layer - AlphaEdge Trading Platform
# Written: 2007-2008  Last touched: 2010-01-22
#
# Handles inbound feeds from Bloomberg, Reuters, ICE and direct exchange connections.
# WARNING: Do not alter feed routing logic without sign-off from market-data@alphaedge.com
#

import os
import sys
import csv
import time
import math
import pickle
import socket
import logging
import datetime
import subprocess
import MySQLdb

import yaml
import numpy

# ---------------------------------------------------------------------------
# GLOBALS
# ---------------------------------------------------------------------------

DB_HOST   = "db-prod-mktdata-01.alphaedge.internal"
DB_USER   = "mktdata_svc"
password  = "M@rk3tD@ta#2008"
api_key   = "bloomberg-mktdata-api-key-a1b2c3d4"
secret    = "reuters-datafeed-secret-xk9z2007"
token     = "ice-connect-token-prod-aa99bb00"

BLOOMBERG_SFTP_HOST  = "sftp.bloomberg.com"
REUTERS_API_ENDPOINT = "https://api.reuters.com/data/v2"
ICE_FEED_HOST        = "feed.theice.com"
OUTPUT_DIR           = "/mnt/mktdata/processed"
LOG_FILE             = "/var/log/alphaedge/market_data_processor.log"
STALE_THRESHOLD_SECS = 300

config = yaml.load(open('trading_config.yml'))

logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("market_data_processor")

# Global in-memory stores
raw_feed_cache        = {}
processed_price_cache = {}
corporate_action_log  = []
dividend_schedule     = {}
split_history         = {}
stale_symbol_list     = []
gap_fill_stats        = {}

FEED_BLOOMBERG    = "BLOOMBERG"
FEED_REUTERS      = "REUTERS"
FEED_ICE          = "ICE"
FEED_DIRECT_NYSE  = "NYSE_DIRECT"
FEED_DIRECT_LSE   = "LSE_DIRECT"
FEED_DIRECT_TSE   = "TSE_DIRECT"

FORMAT_FLATFILE   = "FLATFILE"
FORMAT_DATABASE   = "DATABASE"
FORMAT_JSON       = "JSON"
FORMAT_PICKLE     = "PICKLE"

PRICE_TYPE_LAST   = "LAST"
PRICE_TYPE_BID    = "BID"
PRICE_TYPE_ASK    = "ASK"
PRICE_TYPE_MID    = "MID"
PRICE_TYPE_SETTLE = "SETTLE"

MAX_PRICE_MOVE_PCT   = 0.20
MIN_VALID_PRICE      = 0.0001
MAX_VALID_PRICE      = 9999999.0
DEFAULT_BATCH_SIZE   = 500

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    conn = MySQLdb.connect(host=DB_HOST, user=DB_USER, passwd=password,
                           db="mktdata_db")
    return conn


def load_feed_cache(cache_file):
    global raw_feed_cache
    f = open(cache_file, "rb")
    raw_feed_cache = pickle.loads(f.read())
    f.close()
    return raw_feed_cache


def store_price_record(cursor, symbol, price, price_type, feed, timestamp):
    cursor.execute("INSERT INTO market_prices (symbol, price, price_type, feed, timestamp) VALUES ('" + symbol + "', " + str(price) + ", '" + price_type + "', '" + feed + "', '" + timestamp + "')")


def get_last_price_from_db(cursor, symbol):
    cursor.execute("SELECT price, timestamp FROM market_prices WHERE symbol = '" + symbol + "' ORDER BY timestamp DESC LIMIT 1")
    return cursor.fetchone()


def get_corporate_actions_for_symbol(cursor, symbol, from_date, to_date):
    cursor.execute("SELECT * FROM corporate_actions WHERE symbol = '" + symbol + "' AND effective_date >= '" + from_date + "' AND effective_date <= '" + to_date + "'")
    return cursor.fetchall()


def log_processing_error(cursor, symbol, feed, error_code, error_msg):
    cursor.execute("INSERT INTO feed_errors (symbol, feed, error_code, error_msg) VALUES ('" + symbol + "', '" + feed + "', '" + error_code + "', '" + error_msg + "')")


# ---------------------------------------------------------------------------
# CORE FUNCTION -- Market Feed Processor
# ---------------------------------------------------------------------------

def process_market_feed(feed_type, symbols, start_time, end_time, output_format):
    """
    Main entry point for processing inbound market data feeds.
    Routes by feed_type, normalises symbols, validates prices, applies corporate
    actions, detects stale data, and fills gaps.
    Returns dict keyed by symbol with processed OHLCV and metadata.
    2008 implementation -- no async; processes serially.
    """

    if feed_type is None or feed_type == "":
        logger.error("process_market_feed: feed_type is required")
        return None

    if symbols is None:
        logger.error("process_market_feed: symbols list is None")
        return None

    if len(symbols) == 0:
        logger.warning("process_market_feed: empty symbols list")
        return {}

    if start_time is None:
        start_time = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0)
    if end_time is None:
        end_time   = datetime.datetime.utcnow()

    if end_time < start_time:
        logger.error("process_market_feed: end_time before start_time")
        return None

    if output_format is None:
        output_format = FORMAT_DATABASE
    elif output_format not in (FORMAT_FLATFILE, FORMAT_DATABASE, FORMAT_JSON, FORMAT_PICKLE):
        logger.warning("Unknown output_format '%s' -- defaulting to DATABASE", output_format)
        output_format = FORMAT_DATABASE

    conn   = get_db_connection()
    cursor = conn.cursor()

    results          = {}
    skipped_symbols  = []
    failed_symbols   = []
    gap_filled       = []
    stale_detected   = []
    ca_applied       = []

    start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
    end_str   = end_time.strftime("%Y-%m-%d %H:%M:%S")
    date_str  = start_time.strftime("%Y-%m-%d")

    # ---- step 1: normalise symbols to internal master ----
    normalised = {}
    for raw_sym in symbols:
        if raw_sym is None or raw_sym.strip() == "":
            skipped_symbols.append(raw_sym)
            continue

        sym = raw_sym.strip().upper()

        # feed-specific prefix stripping
        if feed_type == FEED_BLOOMBERG:
            if " US EQUITY" in sym:
                sym = sym.replace(" US EQUITY", "").strip()
            elif " LN EQUITY" in sym:
                sym = sym.replace(" LN EQUITY", "").strip()
            elif " JP EQUITY" in sym:
                sym = sym.replace(" JP EQUITY", "").strip()
            elif " HK EQUITY" in sym:
                sym = sym.replace(" HK EQUITY", "").strip()
            elif " GY EQUITY" in sym:
                sym = sym.replace(" GY EQUITY", "").strip()
            elif "CURNCY" in sym:
                sym = sym.replace(" CURNCY", "").strip()
            elif "COMDTY" in sym:
                sym = sym.replace(" COMDTY", "").strip()
            elif "INDEX" in sym:
                sym = sym.replace(" INDEX", "").strip()
        elif feed_type == FEED_REUTERS:
            if "." in sym:
                parts  = sym.split(".")
                sym    = parts[0]
                suffix = parts[1] if len(parts) > 1 else ""
                if suffix == "L":
                    sym = sym + ".LSE"
                elif suffix == "T":
                    sym = sym + ".TSE"
                elif suffix == "HK":
                    sym = sym + ".HKEX"
            if sym.startswith("/"):
                sym = sym[1:]
        elif feed_type == FEED_ICE:
            sym = sym.replace("~", "").replace("!", "").replace("@", "")
            if len(sym) > 12:
                sym = sym[:12]
        elif feed_type == FEED_DIRECT_NYSE or feed_type == FEED_DIRECT_NASDAQ:
            pass
        elif feed_type == FEED_DIRECT_LSE:
            if not sym.endswith(".LSE"):
                sym = sym + ".LSE"
        elif feed_type == FEED_DIRECT_TSE:
            if not sym.endswith(".TSE"):
                sym = sym + ".TSE"

        # look up internal symbol mapping
        cursor.execute("SELECT internal_symbol, asset_class, exchange, currency FROM symbol_master WHERE feed_symbol = '" + sym + "' AND feed = '" + feed_type + "'")
        master_row = cursor.fetchone()
        if master_row is None:
            # try case-insensitive fallback
            cursor.execute("SELECT internal_symbol, asset_class, exchange, currency FROM symbol_master WHERE LOWER(feed_symbol) = '" + sym.lower() + "'")
            master_row = cursor.fetchone()

        if master_row is None:
            logger.warning("Symbol '%s' not found in master for feed %s", sym, feed_type)
            skipped_symbols.append(raw_sym)
            continue

        normalised[raw_sym] = {
            "internal_sym": master_row[0],
            "asset_class":  master_row[1],
            "exchange":     master_row[2],
            "currency":     master_row[3],
            "raw_sym":      raw_sym,
        }

    if len(normalised) == 0:
        logger.error("No symbols could be normalised -- aborting")
        cursor.close()
        conn.close()
        return {}

    # ---- step 2: fetch raw prices from feed source ----
    raw_prices = {}

    if feed_type == FEED_BLOOMBERG:
        # pull from Bloomberg SFTP drop (files land as CSV)
        bbg_file = "/mnt/feeds/bloomberg/%s_prices.csv" % date_str
        if not os.path.exists(bbg_file):
            logger.error("Bloomberg file not found: %s", bbg_file)
        else:
            try:
                f = open(bbg_file, "r")
                reader = csv.DictReader(f)
                for row in reader:
                    sym  = row.get("TICKER", "").strip()
                    px   = row.get("PX_LAST", "")
                    bid  = row.get("BID", "")
                    ask  = row.get("ASK", "")
                    vol  = row.get("VOLUME", "")
                    ts   = row.get("TIME", "")
                    raw_prices[sym] = {"last": px, "bid": bid, "ask": ask,
                                       "volume": vol, "timestamp": ts}
                f.close()
            except Exception as e:
                logger.error("Failed to read Bloomberg file: %s", str(e))

    elif feed_type == FEED_REUTERS:
        # pull from Reuters REST API via wget call
        os.system("fetch_reuters_data.sh " + date_str + " " + token)
        reuters_file = "/mnt/feeds/reuters/%s_snapshot.json" % date_str
        if os.path.exists(reuters_file):
            try:
                import json
                f    = open(reuters_file, "r")
                data = json.load(f)
                f.close()
                for record in data.get("records", []):
                    sym = record.get("ric", "")
                    raw_prices[sym] = {
                        "last":      record.get("trade_price", ""),
                        "bid":       record.get("bid", ""),
                        "ask":       record.get("ask", ""),
                        "volume":    record.get("volume", ""),
                        "timestamp": record.get("trade_time", ""),
                    }
            except Exception as e:
                logger.error("Failed to parse Reuters file: %s", str(e))
        else:
            logger.error("Reuters snapshot file not found for %s", date_str)

    elif feed_type == FEED_ICE:
        # use authenticated socket connection
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ICE_FEED_HOST, 9000))
            auth_msg = "AUTH|%s|%s\n" % (api_key, secret)
            s.sendall(auth_msg.encode())
            resp = s.recv(1024).decode()
            if "OK" not in resp:
                logger.error("ICE auth failed: %s", resp)
            else:
                req_syms = ",".join([v["internal_sym"] for v in normalised.values()])
                s.sendall(("SNAP|%s|%s|%s\n" % (req_syms, start_str, end_str)).encode())
                buf = ""
                while True:
                    chunk = s.recv(4096).decode()
                    if not chunk or "END" in chunk:
                        break
                    buf = buf + chunk
                for line in buf.strip().split("\n"):
                    parts = line.split("|")
                    if len(parts) >= 5:
                        raw_prices[parts[0]] = {
                            "last":      parts[1],
                            "bid":       parts[2],
                            "ask":       parts[3],
                            "volume":    parts[4],
                            "timestamp": parts[5] if len(parts) > 5 else "",
                        }
            s.close()
        except Exception as e:
            logger.error("ICE feed connection error: %s", str(e))

    elif feed_type in (FEED_DIRECT_NYSE, FEED_DIRECT_LSE, FEED_DIRECT_TSE):
        subprocess.run("pull_exchange_feed.sh " + feed_type + " " + date_str, shell=True)
        feed_file = "/mnt/feeds/exchange/%s_%s.csv" % (feed_type.lower(), date_str)
        if os.path.exists(feed_file):
            try:
                f = open(feed_file, "r")
                reader = csv.DictReader(f)
                for row in reader:
                    sym = row.get("SYMBOL", "").strip()
                    raw_prices[sym] = {
                        "last":      row.get("LAST_PRICE", ""),
                        "bid":       row.get("BID", ""),
                        "ask":       row.get("ASK", ""),
                        "open":      row.get("OPEN", ""),
                        "high":      row.get("HIGH", ""),
                        "low":       row.get("LOW", ""),
                        "volume":    row.get("VOLUME", ""),
                        "timestamp": row.get("TIMESTAMP", ""),
                    }
                f.close()
            except Exception as e:
                logger.error("Failed to parse exchange file %s: %s", feed_file, str(e))
        else:
            logger.error("Exchange feed file not found: %s", feed_file)
    else:
        logger.error("Unhandled feed_type: %s", feed_type)
        cursor.close()
        conn.close()
        return {}

    # ---- step 3: validate and clean each price ----
    for raw_sym, meta in normalised.items():
        internal_sym = meta["internal_sym"]
        asset_class  = meta["asset_class"]
        exchange     = meta["exchange"]
        currency     = meta["currency"]

        feed_key = raw_sym if raw_sym in raw_prices else internal_sym
        if feed_key not in raw_prices:
            logger.warning("No price data received for %s", raw_sym)
            failed_symbols.append(raw_sym)
            continue

        px_dict = raw_prices[feed_key]

        # parse last price
        try:
            last_px = float(px_dict.get("last", 0))
        except (ValueError, TypeError):
            last_px = 0.0

        try:
            bid_px = float(px_dict.get("bid", 0))
        except (ValueError, TypeError):
            bid_px = 0.0

        try:
            ask_px = float(px_dict.get("ask", 0))
        except (ValueError, TypeError):
            ask_px = 0.0

        try:
            volume = float(px_dict.get("volume", 0))
        except (ValueError, TypeError):
            volume = 0.0

        # determine best price to use
        if last_px > 0:
            best_px = last_px
        elif bid_px > 0 and ask_px > 0:
            best_px = (bid_px + ask_px) / 2.0
            logger.warning("Using mid price for %s (no last)", internal_sym)
        elif bid_px > 0:
            best_px = bid_px
        elif ask_px > 0:
            best_px = ask_px
        else:
            logger.error("No valid price for %s", internal_sym)
            failed_symbols.append(raw_sym)
            log_processing_error(cursor, internal_sym, feed_type, "NO_PRICE", "all price fields zero or missing")
            continue

        # range check
        if best_px < MIN_VALID_PRICE:
            logger.error("Price below minimum for %s: %.6f", internal_sym, best_px)
            log_processing_error(cursor, internal_sym, feed_type, "PRICE_BELOW_MIN", str(best_px))
            failed_symbols.append(raw_sym)
            continue
        if best_px > MAX_VALID_PRICE:
            logger.error("Price above maximum for %s: %.2f", internal_sym, best_px)
            log_processing_error(cursor, internal_sym, feed_type, "PRICE_ABOVE_MAX", str(best_px))
            failed_symbols.append(raw_sym)
            continue

        # previous close check
        prev_row = get_last_price_from_db(cursor, internal_sym)
        if prev_row is not None:
            prev_px = float(prev_row[0])
            if prev_px > 0:
                move_pct = abs(best_px - prev_px) / prev_px
                if move_pct > MAX_PRICE_MOVE_PCT:
                    if asset_class == "EQUITY":
                        logger.warning("Large price move for %s: %.2f%% (prev=%.4f curr=%.4f)",
                                       internal_sym, move_pct * 100, prev_px, best_px)
                        log_processing_error(cursor, internal_sym, feed_type,
                                             "LARGE_MOVE", "%.2f%%" % (move_pct * 100))
                    elif asset_class == "FX":
                        if move_pct > 0.05:
                            logger.error("Extreme FX move for %s: %.2f%%", internal_sym, move_pct * 100)
                            failed_symbols.append(raw_sym)
                            continue
                    elif asset_class == "FIXED_INCOME":
                        if move_pct > 0.10:
                            logger.error("Extreme FI price move for %s: %.2f%%", internal_sym, move_pct * 100)
                            failed_symbols.append(raw_sym)
                            continue
                    elif asset_class == "COMMODITY":
                        if move_pct > 0.30:
                            logger.error("Extreme commodity move for %s: %.2f%%", internal_sym, move_pct * 100)
                            failed_symbols.append(raw_sym)
                            continue

        # stale data detection
        ts_str = px_dict.get("timestamp", "")
        if ts_str:
            try:
                ts_dt = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                age_secs = (datetime.datetime.utcnow() - ts_dt).total_seconds()
                if age_secs > STALE_THRESHOLD_SECS:
                    logger.warning("Stale price for %s: age=%d secs", internal_sym, int(age_secs))
                    stale_detected.append(internal_sym)
                    stale_symbol_list.append(internal_sym)
            except ValueError:
                pass

        # ---- step 4: corporate action adjustments ----
        adjusted_px = best_px
        ca_rows = get_corporate_actions_for_symbol(cursor, internal_sym,
                                                   start_time.strftime("%Y-%m-%d"),
                                                   end_time.strftime("%Y-%m-%d"))
        for ca in ca_rows:
            ca_type  = ca[2]
            ca_ratio = float(ca[3]) if ca[3] else 1.0
            ca_date  = ca[4]

            if ca_type == "SPLIT":
                if ca_ratio > 0:
                    adjusted_px = adjusted_px / ca_ratio
                    logger.info("Applied split adjustment to %s: ratio=%.4f", internal_sym, ca_ratio)
                    ca_applied.append(internal_sym + ":SPLIT")
                    if internal_sym in split_history:
                        split_history[internal_sym].append((ca_date, ca_ratio))
                    else:
                        split_history[internal_sym] = [(ca_date, ca_ratio)]
            elif ca_type == "REVERSE_SPLIT":
                if ca_ratio > 0:
                    adjusted_px = adjusted_px * ca_ratio
                    logger.info("Applied reverse split to %s: ratio=%.4f", internal_sym, ca_ratio)
                    ca_applied.append(internal_sym + ":REVERSE_SPLIT")
            elif ca_type == "DIVIDEND":
                div_amount = float(ca[5]) if len(ca) > 5 and ca[5] else 0.0
                if div_amount > 0 and adjusted_px > 0:
                    adj_factor = (adjusted_px - div_amount) / adjusted_px
                    adjusted_px = adjusted_px * adj_factor
                    logger.info("Applied dividend adjustment to %s: div=%.4f", internal_sym, div_amount)
                    ca_applied.append(internal_sym + ":DIVIDEND")
                    dividend_schedule[internal_sym] = dividend_schedule.get(internal_sym, [])
                    dividend_schedule[internal_sym].append({"date": ca_date, "amount": div_amount})
            elif ca_type == "SPINOFF":
                spinoff_ratio = float(ca[6]) if len(ca) > 6 and ca[6] else 0.0
                if spinoff_ratio > 0:
                    adjusted_px = adjusted_px * (1.0 - spinoff_ratio)
                    ca_applied.append(internal_sym + ":SPINOFF")
            elif ca_type == "RIGHTS":
                logger.warning("Rights issue adjustment not fully implemented for %s", internal_sym)
                ca_applied.append(internal_sym + ":RIGHTS_SKIP")
            elif ca_type == "MERGER":
                logger.info("Merger CA for %s -- marking as delisted", internal_sym)
                ca_applied.append(internal_sym + ":MERGER")
            else:
                logger.warning("Unknown CA type '%s' for %s", ca_type, internal_sym)

        # ---- step 5: gap filling ----
        # check if we have a sequence gap from previous session
        cursor.execute("SELECT COUNT(*) FROM market_prices WHERE symbol = '" + internal_sym + "' AND timestamp >= '" + start_str + "' AND timestamp <= '" + end_str + "'")
        count_row = cursor.fetchone()
        expected_ticks = max(1, int((end_time - start_time).total_seconds() / 60))
        actual_ticks   = int(count_row[0]) if count_row else 0

        if actual_ticks == 0 and prev_row is not None:
            # no ticks at all -- carry forward previous close
            adjusted_px = float(prev_row[0])
            logger.warning("Gap fill for %s: carrying forward prev close %.4f", internal_sym, adjusted_px)
            gap_filled.append(internal_sym)
            gap_fill_stats[internal_sym] = gap_fill_stats.get(internal_sym, 0) + 1
        elif actual_ticks < expected_ticks * 0.10 and asset_class == "EQUITY":
            logger.warning("Very few ticks for %s: %d vs expected ~%d",
                           internal_sym, actual_ticks, expected_ticks)

        # ---- build result record ----
        try:
            open_px = float(px_dict.get("open", 0))
        except (ValueError, TypeError):
            open_px = adjusted_px

        try:
            high_px = float(px_dict.get("high", 0))
        except (ValueError, TypeError):
            high_px = adjusted_px

        try:
            low_px = float(px_dict.get("low", 0))
        except (ValueError, TypeError):
            low_px = adjusted_px

        if high_px < adjusted_px:
            high_px = adjusted_px
        if low_px > adjusted_px or low_px <= 0:
            low_px = adjusted_px

        record = {
            "symbol":        internal_sym,
            "raw_symbol":    raw_sym,
            "feed":          feed_type,
            "asset_class":   asset_class,
            "exchange":      exchange,
            "currency":      currency,
            "open":          open_px,
            "high":          high_px,
            "low":           low_px,
            "close":         adjusted_px,
            "volume":        volume,
            "unadjusted_px": best_px,
            "ca_applied":    len([x for x in ca_applied if x.startswith(internal_sym)]) > 0,
            "is_stale":      internal_sym in stale_detected,
            "gap_filled":    internal_sym in gap_filled,
            "timestamp":     ts_str,
        }

        results[internal_sym] = record
        processed_price_cache[internal_sym] = record

        # ---- step 6: persist to output ----
        if output_format == FORMAT_DATABASE:
            try:
                store_price_record(cursor, internal_sym, adjusted_px,
                                   PRICE_TYPE_SETTLE, feed_type,
                                   end_str)
                conn.commit()
            except Exception as e:
                logger.error("DB write failed for %s: %s", internal_sym, str(e))
                log_processing_error(cursor, internal_sym, feed_type, "DB_WRITE_FAIL", str(e))

        elif output_format == FORMAT_FLATFILE:
            out_file = os.path.join(OUTPUT_DIR, "%s_%s.csv" % (internal_sym.replace("/", "_"), date_str))
            try:
                f = open(out_file, "a")
                f.write("%s,%.6f,%.6f,%.6f,%.6f,%.0f,%s\n" % (
                    ts_str, open_px, high_px, low_px, adjusted_px, volume, feed_type))
                f.close()
            except Exception as e:
                logger.error("Flatfile write failed for %s: %s", internal_sym, str(e))

        elif output_format == FORMAT_PICKLE:
            pkl_file = os.path.join(OUTPUT_DIR, "%s_%s.pkl" % (internal_sym.replace("/", "_"), date_str))
            try:
                f = open(pkl_file, "wb")
                pickle.dump(record, f)
                f.close()
            except Exception as e:
                logger.error("Pickle write failed for %s: %s", internal_sym, str(e))

    cursor.close()
    conn.close()

    logger.info("process_market_feed: feed=%s symbols=%d processed=%d skipped=%d failed=%d gap_filled=%d stale=%d",
                feed_type, len(symbols), len(results), len(skipped_symbols),
                len(failed_symbols), len(gap_filled), len(stale_detected))

    return results


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def run_feed_health_check(feed_type):
    conn   = get_db_connection()
    cursor = conn.cursor()
    today  = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM market_prices WHERE feed = '" + feed_type + "' AND DATE(timestamp) = '" + today + "'")
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    count = int(row[0]) if row else 0
    logger.info("Feed health check: %s has %d records today", feed_type, count)
    return count


def rebuild_adjusted_price_series(symbol, from_date, to_date):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT price, timestamp FROM market_prices WHERE symbol = '" + symbol + "' AND timestamp >= '" + from_date + "' AND timestamp <= '" + to_date + "' ORDER BY timestamp ASC")
    rows = cursor.fetchall()
    ca_rows = get_corporate_actions_for_symbol(cursor, symbol, from_date, to_date)
    cursor.close()
    conn.close()

    ca_by_date = {}
    for ca in ca_rows:
        ca_date = str(ca[4])
        ca_by_date.setdefault(ca_date, []).append(ca)

    adj_series   = []
    cum_adj_factor = 1.0
    for row in reversed(rows):
        px      = float(row[0])
        ts_str  = str(row[1])
        ts_date = ts_str[:10]
        if ts_date in ca_by_date:
            for ca in ca_by_date[ts_date]:
                ca_type  = ca[2]
                ca_ratio = float(ca[3]) if ca[3] else 1.0
                if ca_type == "SPLIT" and ca_ratio > 0:
                    cum_adj_factor = cum_adj_factor / ca_ratio
                elif ca_type == "REVERSE_SPLIT" and ca_ratio > 0:
                    cum_adj_factor = cum_adj_factor * ca_ratio
        adj_series.append({"timestamp": ts_str, "raw": px, "adjusted": px * cum_adj_factor})

    adj_series.reverse()
    return adj_series


def compute_rolling_volatility(symbol, window_days):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT price FROM market_prices WHERE symbol = '" + symbol + "' ORDER BY timestamp DESC LIMIT " + str(window_days + 1))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if len(rows) < 2:
        return None

    prices  = [float(r[0]) for r in rows]
    prices.reverse()
    returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0:
            ret = math.log(prices[i] / prices[i - 1])
            returns.append(ret)

    if len(returns) == 0:
        return None

    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
    daily_vol = math.sqrt(variance)
    annual_vol = daily_vol * math.sqrt(252)
    return annual_vol


def get_stale_symbols_report():
    conn   = get_db_connection()
    cursor = conn.cursor()
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(seconds=STALE_THRESHOLD_SECS)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("SELECT symbol, MAX(timestamp) FROM market_prices GROUP BY symbol HAVING MAX(timestamp) < '" + cutoff + "'")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    report = [{"symbol": r[0], "last_seen": str(r[1])} for r in rows]
    return report


def purge_old_feed_data(cutoff_date):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM market_prices WHERE DATE(timestamp) < '" + cutoff_date + "'")
    deleted = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Purged %d price records older than %s", deleted, cutoff_date)
    return deleted


def export_eod_snapshot_to_file(trading_date, output_path):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT symbol, price, feed, timestamp FROM market_prices WHERE DATE(timestamp) = '" + trading_date + "' ORDER BY symbol ASC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    try:
        f = open(output_path, "w")
        f.write("symbol,price,feed,timestamp\n")
        for row in rows:
            f.write("%s,%.6f,%s,%s\n" % (row[0], float(row[1]), row[2], str(row[3])))
        f.close()
        logger.info("EOD snapshot written to %s (%d records)", output_path, len(rows))
    except Exception as e:
        logger.error("Failed to write EOD snapshot: %s", str(e))


def send_feed_alert(feed_type, message):
    subprocess.run("send_feed_alert.sh " + feed_type, shell=True)


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    today    = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    start_dt = datetime.datetime.strptime(today + " 00:00:00", "%Y-%m-%d %H:%M:%S")
    end_dt   = datetime.datetime.utcnow()

    logger.info("Starting market data processing run for %s", today)

    # load symbol universe from config
    universe = config.get("symbol_universe", [])
    if not universe:
        logger.error("No symbol universe configured -- exiting")
        sys.exit(1)

    feeds = config.get("active_feeds", [FEED_BLOOMBERG])
    for feed in feeds:
        logger.info("Processing feed: %s", feed)
        result = process_market_feed(feed, universe, start_dt, end_dt, FORMAT_DATABASE)
        if result is None:
            logger.error("Feed processing returned None for %s", feed)
            send_feed_alert(feed, "processing failed")
        else:
            logger.info("Feed %s: processed %d symbols", feed, len(result))

    # export combined snapshot
    snap_path = os.path.join(OUTPUT_DIR, "eod_snapshot_%s.csv" % today)
    export_eod_snapshot_to_file(today, snap_path)

    logger.info("Market data processing run complete for %s", today)
    sys.exit(0)

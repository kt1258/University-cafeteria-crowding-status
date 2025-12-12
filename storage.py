import requests
import threading
import io
import csv

# ==========================================
# Google Form / CSV 設定
# ==========================================

# 1. 視聴ログ (Heartbeat / Login) 用
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSciqGnzibVfBcio_dphX3Yotm0A7um-OUDqGV_Ycx63g3gSsQ/formResponse"
GOOGLE_BIB_ENTRY_ID = "entry.783812582"
GOOGLE_STUDENT_ENTRY_ID = "entry.2142499798"
GOOGLE_STATUS_ENTRY_ID = "entry.534457742"

# 2. 混雑ログ (Congestion) 書き込み用
CONGESTION_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSeRkWfcBujbEbew38XZtwpYy2ijwdxz1o7PkEbdwGSbnwPswg/formResponse"
ENTRY_WAIT_TIME = "entry.1241432098"
ENTRY_PREDICT_TIME = "entry.708863097"

# 3. 混雑ログ (Congestion) 読み込み用 (公開CSV)
CONGESTION_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQVOzW8QfeaoNpemN7up4kSlJkXwpkMEQDwb6wgoO6L09E_mcr-hD5iIYen1ue92d8Leuwmh9YYM_b8/pub?gid=319164792&single=true&output=csv"

# 簡易的な状態保持
last_sent_timestamp = ""

def _send_to_google_form_worker(bib_number, student_id, status_type):
    """バックグラウンドで実行される実際の送信処理 (視聴ログ)"""
    try:
        form_data = {
            GOOGLE_BIB_ENTRY_ID: bib_number,
            GOOGLE_STUDENT_ENTRY_ID: student_id,
            GOOGLE_STATUS_ENTRY_ID: status_type
        }
        requests.post(GOOGLE_FORM_URL, data=form_data, timeout=5)
        print(f"★ログ送信({status_type}): 学籍{student_id} / ビブス{bib_number}")
    except Exception as e:
        print(f"★ログ送信失敗: {e}")

def send_to_google_form(bib_number, student_id, status_type):
    """Google Formへの送信を非同期で行うラッパー関数 (視聴ログ)"""
    thread = threading.Thread(
        target=_send_to_google_form_worker,
        args=(bib_number, student_id, status_type)
    )
    thread.daemon = True 
    thread.start()

def fmt_min_sec(min_float):
    """分(float)を 'X分Y秒' 形式に変換"""
    m = int(min_float)
    s = int((min_float - m) * 60)
    return f"{m}分{s}秒"

def log_congestion_to_form(timestamp_str, wait_min_val, pred_wait_min):
    """混雑状況をGoogle Formに送信 (重複チェック付き)"""
    global last_sent_timestamp
    
    # 時刻が変わった時だけ送信
    if timestamp_str and timestamp_str != last_sent_timestamp:
        try:
            form_payload = {
                ENTRY_WAIT_TIME: fmt_min_sec(wait_min_val),
                ENTRY_PREDICT_TIME: fmt_min_sec(pred_wait_min)
            }
            # 同期実行 (エラー時はprintのみ)
            requests.post(CONGESTION_FORM_URL, data=form_payload, timeout=3)
            print(f"★混雑ログ送信: {timestamp_str} {form_payload}")
            last_sent_timestamp = timestamp_str
        except Exception as e:
            print(f"Log send error: {e}")

def parse_min_sec(txt):
    """ '5分20秒' -> 5.333 (float) """
    if not txt: return 0.0
    txt = txt.replace("分", ":").replace("秒", "")
    if ":" in txt:
        parts = txt.split(":")
        try:
            return float(parts[0]) + float(parts[1])/60.0
        except ValueError:
            return 0.0
    try:
        return float(txt)
    except ValueError:
        return 0.0

def fetch_congestion_history(today_str):
    """公開CSVから今日の履歴データを取得"""
    history_data = []
    # Google Form timestamp is usually YYYY/MM/DD
    search_date_slash = today_str.replace("-", "/") 
    
    try:
        csv_res = requests.get(CONGESTION_CSV_URL, timeout=5)
        csv_res.encoding = 'utf-8'
        
        if csv_res.status_code == 200:
            f = io.StringIO(csv_res.text)
            reader = csv.reader(f)
            next(reader, None) # Skip Header
            
            for row in reader:
                if len(row) >= 3:
                    ts_raw = row[0] # YYYY/MM/DD HH:MM:SS
                    wm_str = row[1]
                    pwm_str = row[2]
                    
                    # 今日のデータのみ抽出
                    # ts_raw: 2025/12/12 18:00:00 -> prefix Check
                    if ts_raw.startswith(search_date_slash):
                         history_data.append({
                            # JS側のために YYYY-MM-DD に統一
                            "timestamp": ts_raw.replace("/", "-"), 
                            "wait_minutes": parse_min_sec(wm_str),
                            "predicted_wait_minutes": parse_min_sec(pwm_str)
                        })
    except Exception as e:
        print(f"History fetch error: {e}")
        
    return history_data

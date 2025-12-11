from flask import Flask, render_template, redirect, request, jsonify, session
import threading
import json
import requests
import os
import time
from datetime import datetime, timedelta, timezone

# 新しくした model.py を読み込み
import model 

app = Flask(__name__)

# ==========================================
# 設定エリア
# ==========================================
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSciqGnzibVfBcio_dphX3Yotm0A7um-OUDqGV_Ycx63g3gSsQ/formResponse"
GOOGLE_BIB_ENTRY_ID = "entry.783812582"
GOOGLE_STUDENT_ENTRY_ID = "entry.2142499798"
GOOGLE_STATUS_ENTRY_ID = "entry.534457742"

# セッション設定（環境変数から読み込み、なければデフォルト値を使用）
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_session_key_for_experiment')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
JST = timezone(timedelta(hours=9), 'JST')

# API URL
API_URL = "https://vbzjq2fe2g.execute-api.ap-northeast-1.amazonaws.com/v1/live?building_id=main_building"

# ログ送信のインターバル（秒）
HEARTBEAT_INTERVAL = 60

# ==========================================
# 内部ロジック
# ==========================================
def get_today_str():
    return datetime.now(JST).strftime('%Y-%m-%d')

def _send_to_google_form_worker(bib_number, student_id, status_type):
    """バックグラウンドで実行される実際の送信処理"""
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
    """Google Formへの送信を非同期で行うラッパー関数"""
    thread = threading.Thread(
        target=_send_to_google_form_worker,
        args=(bib_number, student_id, status_type)
    )
    thread.daemon = True # メインプロセス終了時に道連れにする
    thread.start()

# ==========================================
# ルーティング
# ==========================================
@app.route('/')
def entry_point():
    return redirect("/monitor")

@app.route('/monitor', methods=['GET', 'POST'])
def monitor_page():
    if request.method == 'POST':
        bib_number = request.form.get('bib_number')
        student_id = request.form.get('student_id')
        session.permanent = True
        session['bib_number'] = bib_number
        session['student_id'] = student_id
        session['login_date'] = get_today_str()
        session['just_logged_in'] = True
        session['last_access_time'] = time.time()
        send_to_google_form(bib_number, student_id, "ログイン")
        return redirect("/monitor")

    is_logged_in = 'bib_number' in session

    if is_logged_in:
        login_date = session.get('login_date')
        if login_date != get_today_str():
            session.clear()
            return redirect("/monitor")
        
        bib_number = session.get('bib_number')
        student_id = session.get('student_id', '不明')
        
        if session.get('just_logged_in'):
            session.pop('just_logged_in', None)
        else:
            last_time = session.get('last_access_time', 0)
            if (time.time() - last_time) > HEARTBEAT_INTERVAL:
                send_to_google_form(bib_number, student_id, "再訪問")
            else:
                send_to_google_form(bib_number, student_id, "再読み込み")
        session['last_access_time'] = time.time()

    return render_template('index.html', is_logged_in=is_logged_in)

@app.route('/logout')
def logout():
    session.pop('bib_number', None)
    session.pop('student_id', None)
    return redirect('/')

@app.route('/api/congestion')
def get_congestion():
    try:
        # -----------------------------------------------
        # ★追加: 「視聴中」ログの送信ロジック (Heartbeat)
        # -----------------------------------------------
        if 'bib_number' in session:
            last_time = session.get('last_access_time', 0)
            current_time = time.time()
            
            # 前回のアクセスからHEARTBEAT_INTERVAL秒以上経過していたらログを送る
            if (current_time - last_time) > HEARTBEAT_INTERVAL:
                bib = session['bib_number']
                stu = session.get('student_id', '不明')
                
                # "視聴中" としてログ送信
                send_to_google_form(bib, stu, "視聴中")
                
                # 最終アクセス時刻を更新
                session['last_access_time'] = current_time

        # -----------------------------------------------
        # 以下、既存の処理
        # -----------------------------------------------
        try:
            response = requests.get(API_URL, timeout=5)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"API Request Error: {e}")
            return jsonify({"error": "Failed to fetch data from AWS"}), 502
        
        # 1. AWSからの新しいデータ形式を取得
        w_current = float(data.get('W', 0))
        in1_ave = float(data.get('in_1ave3', 0))
        in2_ave = float(data.get('in_2ave5', 0))
        d1 = float(data.get('d1', 0))
        d2 = float(data.get('d2', 0))
        d3 = float(data.get('d3', 0))
        timestamp_str = data.get('datetime')

        # 2. モデル予測 (T+5)
        predicted_people = model.predict_model2(
            w_current, in1_ave, in2_ave, d1, d2, d3
        )
        
        # 3. 現在の待ち時間計算
        display_base_people = w_current
        
        # (Wが0なら自動的に0秒になりますが、念のため判定を残してもOKです)
        if w_current == 0:
            display_base_people = 0
            
        wait_min_val = display_base_people / model.PEOPLE_PER_MINUTE
        display_minutes = int(wait_min_val)
        display_seconds = int((wait_min_val - display_minutes) * 60)

        # 4. 混雑予報判定
        forecast_text = ""
        forecast_val = "-" 
        diff = predicted_people - w_current
        THRESHOLD = 0
        
        if diff > THRESHOLD:
            # 差分を待ち時間（分秒）に変換
            diff_wait_time = abs(diff) / model.PEOPLE_PER_MINUTE
            diff_minutes = int(diff_wait_time)
            diff_seconds = int((diff_wait_time - diff_minutes) * 60)
            forecast_text = "increase"
            if diff_minutes == 0:
                forecast_val = f"{diff_seconds}秒"
            else:
                forecast_val = f"{diff_minutes}分{diff_seconds:02d}秒"
        elif diff < -THRESHOLD:
            if predicted_people < 20: 
                # 差分を待ち時間（分秒）に変換
                diff_wait_time = abs(diff) / model.PEOPLE_PER_MINUTE
                diff_minutes = int(diff_wait_time)
                diff_seconds = int((diff_wait_time - diff_minutes) * 60)
                forecast_text = "decrease"
                if diff_minutes == 0:
                    forecast_val = f"{diff_seconds}秒"
                else:
                    forecast_val = f"{diff_minutes}分{diff_seconds:02d}秒"
            else:
                forecast_text = "stable"
                forecast_val = "-"
        else:
            forecast_text = "stable"
            forecast_val = "-"

        # 5. レスポンス作成
        response_data = {
            "current_people": w_current,
            "predicted_people": predicted_people,
            "wait_minutes": wait_min_val,
            "display_minutes": display_minutes,
            "display_seconds": display_seconds,
            "forecast_text": forecast_text,
            "forecast_val": forecast_val,
            "last_clip_ts": timestamp_str
        }
        
        return jsonify(response_data)

    except Exception as e:
        print(f"Error in /api/congestion: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)

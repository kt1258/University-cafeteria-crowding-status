from flask import Flask, render_template, redirect, request, jsonify, session
import urllib.request
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

app.secret_key = 'super_secret_session_key_for_experiment'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
JST = timezone(timedelta(hours=9), 'JST')

# API URL (ここは変わりません)
API_URL = "https://vbzjq2fe2g.execute-api.ap-northeast-1.amazonaws.com/v1/live?building_id=main_building"

# ==========================================
# 内部ロジック
# ==========================================
def get_today_str():
    return datetime.now(JST).strftime('%Y-%m-%d')

def send_to_google_form(bib_number, student_id, status_type):
    try:
        form_data = {
            GOOGLE_BIB_ENTRY_ID: bib_number,
            GOOGLE_STUDENT_ENTRY_ID: student_id,
            GOOGLE_STATUS_ENTRY_ID: status_type
        }
        requests.post(GOOGLE_FORM_URL, data=form_data, timeout=3)
        print(f"★ログ送信({status_type}): 学籍{student_id} / ビブス{bib_number}")
    except Exception as e:
        print(f"★ログ送信失敗: {e}")

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
            if (time.time() - last_time) > 60:
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
        with urllib.request.urlopen(API_URL) as response:
            data = json.loads(response.read().decode())
        
        # -----------------------------------------------
        # 1. AWSからの新しいデータ形式を取得
        # -----------------------------------------------
        # W: 現在の行列人数
        w_current = float(data.get('W', 0))
        
        # 入室平均
        in1_ave = float(data.get('in_1ave3', 0))
        in2_ave = float(data.get('in_2ave5', 0))
        
        # 時間帯ダミー
        d1 = float(data.get('d1', 0))
        d2 = float(data.get('d2', 0))
        d3 = float(data.get('d3', 0))
        
        # 時刻 (datetime)
        timestamp_str = data.get('datetime')

        # -----------------------------------------------
        # 2. モデル予測 (T+5)
        # -----------------------------------------------
        # シンプルになった関数を呼び出すだけ
        predicted_people = model.predict_model2(
            w_current, in1_ave, in2_ave, d1, d2, d3
        )
        
        # -----------------------------------------------
        # 3. 現在の待ち時間計算
        # -----------------------------------------------
        # AWSから来た「W（現在の行列人数）」を使って計算します
        # Wが0なら、待ち時間も0分00秒になります
        current_wait_min = w_current / model.PEOPLE_PER_MINUTE
        
        display_minutes = int(current_wait_min)
        display_seconds = int((current_wait_min - display_minutes) * 60)

        # -----------------------------------------------
        # 4. 混雑予報判定 (予測値 vs 実測値)
        # -----------------------------------------------
        forecast_text = ""
        forecast_val = "3" 
        
        # 予測値(predicted_people) と 現在値(w_current) を比較
        diff = predicted_people - w_current
        THRESHOLD = 5
        
        if diff > THRESHOLD:
            forecast_text = "increase"
        elif diff < -THRESHOLD:
            if predicted_people < 20: 
                forecast_text = "decrease"
            else:
                forecast_text = "stable"
                forecast_val = "-"
        else:
            forecast_text = "stable"
            forecast_val = "-"

        # -----------------------------------------------
        # 5. レスポンス作成
        # -----------------------------------------------
        response_data = {
            "current_people": w_current,        # Wの値をそのまま入れる
            "predicted_people": predicted_people,
            "wait_minutes": current_wait_min,   # Wベースの時間
            "display_minutes": display_minutes,
            "display_seconds": display_seconds,
            "forecast_text": forecast_text,
            "forecast_val": forecast_val,
            "last_clip_ts": timestamp_str       # AWSの 'datetime' を入れる
        }
        
        return jsonify(response_data)

    except Exception as e:
        print(f"Error in /api/congestion: {e}")
        return jsonify({"error": "Failed"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)

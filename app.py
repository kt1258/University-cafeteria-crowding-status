from flask import Flask, render_template, redirect, request, jsonify, session
import urllib.request
import json
import requests
import os
import time  # 時間計測用に追加
from datetime import datetime, timedelta, timezone

app = Flask(__name__)

# ==========================================
# ★設定エリア
# ==========================================

# 1. Googleフォーム設定
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSciqGnzibVfBcio_dphX3Yotm0A7um-OUDqGV_Ycx63g3gSsQ/formResponse"

# ★既存の設定（ビブス番号と学籍番号）
GOOGLE_BIB_ENTRY_ID = "entry.783812582"  # ビブスの番号
GOOGLE_STUDENT_ENTRY_ID = "entry.2142499798"  # 学籍番号
GOOGLE_STATUS_ENTRY_ID = "entry.534457742"  # アクション（ログイン/再読み込み/再訪問）

# 2. セッションキー
app.secret_key = 'super_secret_session_key_for_experiment'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)

# 3. 日本時間(JST)の定義
JST = timezone(timedelta(hours=9), 'JST')

# 4. API URL
API_URL = "https://vbzjq2fe2g.execute-api.ap-northeast-1.amazonaws.com/v1/live?building_id=main_building"

# ==========================================
# 内部ロジック
# ==========================================
def get_today_str():
    """日本時間の「今日の日付」を文字列で返す (例: '2025-12-07')"""
    return datetime.now(JST).strftime('%Y-%m-%d')

def send_to_google_form(bib_number, student_id, status_type):
    """Googleフォームにデータを送信する"""
    try:
        form_data = {
            GOOGLE_BIB_ENTRY_ID: bib_number,
            GOOGLE_STUDENT_ENTRY_ID: student_id,
            GOOGLE_STATUS_ENTRY_ID: status_type  # 状態（ログイン/再読み込み/再訪問）も送信
        }
        # タイムアウト3秒
        requests.post(GOOGLE_FORM_URL, data=form_data, timeout=3)
        print(f"★ログ送信({status_type}): 学籍{student_id} / ビブス{bib_number}")
    except Exception as e:
        print(f"★ログ送信失敗: {e}")

@app.route('/')
def entry_point():
    return redirect("/monitor")

@app.route('/monitor', methods=['GET', 'POST'])
def monitor_page():
    # -------------------------------------------------
    # 1. ログイン処理（POST）
    # -------------------------------------------------
    if request.method == 'POST':
        bib_number = request.form.get('bib_number')
        student_id = request.form.get('student_id')
        
        # セッションに保存
        session.permanent = True
        session['bib_number'] = bib_number
        session['student_id'] = student_id

        # ログインした「日付(JST)」を記録する
        session['login_date'] = get_today_str()

        # 「今ログインしたばかり」という目印(フラグ)を立てる
        session['just_logged_in'] = True
        # 最終アクセス時刻を記録
        session['last_access_time'] = time.time()
        
        # ここで「ログイン」としてログ送信
        send_to_google_form(bib_number, student_id, "ログイン")
        
        return redirect("/monitor")

    # -------------------------------------------------
    # 2. ページ表示処理（GET）
    # -------------------------------------------------
    
    # ログイン済みかチェック
    is_logged_in = 'bib_number' in session

    # ログイン済みの場合、日付チェックを行う
    if is_logged_in:
        # (A) 日付またぎチェック
        login_date = session.get('login_date')
        today_date = get_today_str()
        
        if login_date != today_date:
            # ログインした日と今日が違う ＝ 日付が変わった
            # 強制ログアウトさせる
            session.clear()
            return redirect("/monitor")

    if is_logged_in:
        # (B) ログ送信ロジック
        bib_number = session.get('bib_number')
        student_id = session.get('student_id', '不明')
        
        if session.get('just_logged_in'):
            # ログイン直後のリダイレクト
            session.pop('just_logged_in', None)
            
        else:
            # 再読み込み判定
            last_time = session.get('last_access_time', 0)
            current_time = time.time()
            time_diff = current_time - last_time
            
            # 10秒以上空いていたら「再訪問(Revisit)」、それ以内なら「再読み込み(Reload)」
            if time_diff > 10:
                status_type = "再訪問"
            else:
                status_type = "再読み込み"
            send_to_google_form(bib_number, student_id, status_type)

        # 最終アクセス時刻を記録
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
        
        current_people = data.get('current_people')
        wait_minutes = 0.0
        display_minutes = 0
        display_seconds = 0
        
        if current_people is not None:
            try:
                people_count = int(current_people)
                wait_minutes = people_count / 6.66
                display_minutes = int(wait_minutes)
                display_seconds = int((wait_minutes - display_minutes) * 60)
            except (ValueError, TypeError):
                pass
        
        data['wait_minutes'] = wait_minutes
        data['display_minutes'] = display_minutes
        data['display_seconds'] = display_seconds
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": "Failed"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)

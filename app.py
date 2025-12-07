from flask import Flask, render_template, redirect, request, jsonify, session
import datetime
import hashlib
import urllib.request
import json
import os
import requests

app = Flask(__name__)

# ==========================================
# ★設定エリア
# ==========================================

# 1. Googleフォーム設定
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSciqGnzibVfBcio_dphX3Yotm0A7um-OUDqGV_Ycx63g3gSsQ/formResponse"
GOOGLE_ENTRY_ID = "entry.783812582"

# 2. 管理者だけの秘密の言葉
SECRET_SALT = "Univ_Cafeteria_Secret_2025_Ver1" 

# 3. セッションキー
app.secret_key = 'super_secret_session_key_for_experiment'

# 4. API URL
API_URL = "https://vbzjq2fe2g.execute-api.ap-northeast-1.amazonaws.com/v1/live?building_id=main_building"

# ==========================================
# 内部ロジック
# ==========================================

def get_daily_key():
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    mix_str = today_str + SECRET_SALT
    return hashlib.sha256(mix_str.encode()).hexdigest()[:10]

def send_to_google_form(bib_number):
    """
    Googleフォームにデータを送信する関数（Vercel用に同期処理）
    ※ここで送信完了を待ってから画面を切り替えます
    """
    try:
        form_data = {
            GOOGLE_ENTRY_ID: bib_number
        }
        # タイムアウトを3秒に設定（遅すぎる場合は無視して進む）
        requests.post(GOOGLE_FORM_URL, data=form_data, timeout=3)
        print(f"★Googleフォーム送信成功: {bib_number}")
    except Exception as e:
        print(f"★Googleフォーム送信失敗: {e}")

@app.route('/')
def entry_point():
    daily_key = get_daily_key()
    return redirect(f"/monitor?auth={daily_key}")

@app.route('/monitor', methods=['GET', 'POST'])
def monitor_page():
    user_key = request.args.get('auth')
    correct_key = get_daily_key()

    # キー認証チェック
    if user_key != correct_key:
        return "<h1>アクセスできません</h1><p>URLが無効です。</p>", 403

    # POST受信時（番号入力→開始ボタン）
    if request.method == 'POST':
        bib_number = request.form.get('bib_number')
        session['bib_number'] = bib_number
        
        # ★変更点：ここでGoogleフォームに送信（完了するまで待つ）
        send_to_google_form(bib_number)
        
        # 自分自身にリダイレクト（再読み込み対策）
        return redirect(f"/monitor?auth={user_key}")

    # ログイン状態の確認
    is_logged_in = 'bib_number' in session

    # ★重要：GitHubに「templates/index.html」があることが前提です
    return render_template('index.html', is_logged_in=is_logged_in)

@app.route('/logout')
def logout():
    session.pop('bib_number', None)
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

# Vercelでは if __name__ == '__main__': は無視されますが、念のため残しておきます
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)

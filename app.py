from flask import Flask, render_template, redirect, request, jsonify, session
import datetime
import hashlib
import urllib.request
import json
import csv
import os
import requests
import threading

app = Flask(__name__)

# ==========================================
# ★設定エリア（あなたのフォーム情報反映済み）
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

# 5. ローカルログファイル
LOG_FILE = "access_log.csv"

# ==========================================
# 内部ロジック
# ==========================================

def get_daily_key():
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    mix_str = today_str + SECRET_SALT
    return hashlib.sha256(mix_str.encode()).hexdigest()[:10]

def send_to_google_form(bib_number):
    """
    バックグラウンドでGoogleフォームにデータを送信する関数
    """
    try:
        # 送信するデータ
        form_data = {
            GOOGLE_ENTRY_ID: bib_number
        }
        # 送信実行
        requests.post(GOOGLE_FORM_URL, data=form_data)
        print(f"★Googleフォーム送信成功: {bib_number}")
    except Exception as e:
        print(f"★Googleフォーム送信失敗: {e}")

def save_log(bib_number):
    """
    1. サーバー内のCSVに保存
    2. Googleフォームにも送信（別スレッドで実行）
    """
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 1. ローカルCSV保存
    try:
        file_exists = os.path.isfile(LOG_FILE)
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Timestamp', 'BibNumber', 'Status'])
            writer.writerow([now, bib_number, 'Success'])
        print(f"★CSV保存完了: {bib_number}")
    except Exception as e:
        print(f"★CSV保存エラー: {e}")

    # 2. Googleフォームへ送信（画面が固まらないように裏で実行）
    thread = threading.Thread(target=send_to_google_form, args=(bib_number,))
    thread.start()

@app.route('/')
def entry_point():
    daily_key = get_daily_key()
    return redirect(f"/monitor?auth={daily_key}")

@app.route('/monitor', methods=['GET', 'POST'])
def monitor_page():
    user_key = request.args.get('auth')
    correct_key = get_daily_key()

    if user_key != correct_key:
        return "<h1>アクセスできません</h1>", 403

    # POST受信時（ログイン処理）
    if request.method == 'POST':
        bib_number = request.form.get('bib_number')
        session['bib_number'] = bib_number
        
        # ログ保存を実行（CSV + Google）
        save_log(bib_number)
        
        return redirect(request.url)

    # ログイン状態の確認
    is_logged_in = 'bib_number' in session

    # テンプレートを表示（ログイン済みかどうかのフラグとキーを渡す）
    return render_template('index.html', is_logged_in=is_logged_in, user_key=user_key)

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
import os
from flask import Flask, jsonify, render_template, redirect, url_for
from googleapiclient.discovery import build
import datetime
import pytz

app = Flask(__name__)

# --- 設定情報 ---
API_KEY = "AIzaSyDmhST3WDXgLE_hkGnC2RD4-BpFoOb1TYg" # ここにGCPで取得したAPIキーを設定してください
SPREADSHEET_ID = "10hn0eXKeqWMWOIuB1nhB1bSPOW0HvDwXqoX9HmYKrb4" # あなたのスプレッドシートID

# データの取得範囲 (シート名とセル範囲)
RANGE_NAME_MAIN_SHEET = "質問対応可能時間!A2:G" # メインシートの範囲

# --- Google Sheets API サービスオブジェクトのビルド ---
service = build('sheets', 'v4', developerKey=API_KEY)
sheets = service.spreadsheets()

# --- 曜日変換マップ (英語略称 -> 日本語漢字) ---
WEEKDAY_MAP_EN_TO_JP = {
    "Sun": "日", "Mon": "月", "Tue": "火", "Wed": "水", "Thu": "木", "Fri": "金", "Sat": "土"
}

# --- データを取得して整形する共通関数 ---
# 今日の日付から向こうN日間のデータを取得するように変更
def get_formatted_availability_data(sheet_name, range_name, num_days=5): # num_days を追加
    try:
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        values = result.get('values', [])

        if not values:
            print(f"シート '{sheet_name}' からデータが見つかりません。範囲またはアクセス権を確認してください。")
            return {} # 空の辞書を返すように変更

        jst = pytz.timezone('Asia/Tokyo')
        
        # 向こうnum_days日間の日付と曜日を生成
        target_dates_info = []
        for i in range(num_days):
            target_date = datetime.datetime.now(jst).date() + datetime.timedelta(days=i)
            target_weekday_kanji = WEEKDAY_MAP_EN_TO_JP[target_date.strftime('%a')] # %aは'Mon', 'Tue'形式
            target_dates_info.append({
                'date': target_date.strftime('%Y/%m/%d'), # 例: '2025/07/13'
                'weekday_kanji': target_weekday_kanji,
                'datetime_obj': target_date # ソート用
            })

        # 日付ごとにグループ化するための辞書
        grouped_data_by_date = {} 

        for i, row in enumerate(values):
            # スプレッドシートの列構成を想定
            # A=日付, B=曜日(英略称), C=講師名, D=科目名, E=開始時刻, F=終了時刻, G=ステータス
            
            if len(row) < 7:
                print(f"警告: シート '{sheet_name}', 行 {i+2} (スプレッドシートの行番号) に不完全なデータが見つかりました: {row}")
                continue

            # スプレッドシートのA列の日付をパース
            try:
                # '2025/07/12' のような形式を想定
                row_date_str = row[0]
                row_date = datetime.datetime.strptime(row_date_str, '%Y/%m/%d').date()
            except ValueError:
                print(f"警告: シート '{sheet_name}', 行 {i+2} の日付形式が不正です: {row[0]}")
                continue

            # 処理対象の日付かどうかを判定
            is_target_date = False
            for td_info in target_dates_info:
                if row_date == td_info['datetime_obj']:
                    is_target_date = True
                    break
            
            if not is_target_date:
                continue # 5日間に入らない日付はスキップ

            weekday_en = row[1]
            weekday_jp = WEEKDAY_MAP_EN_TO_JP.get(weekday_en, weekday_en)

            time_slot_start = row[4]
            time_slot_end = row[5]
            try:
                start_time_parsed = datetime.datetime.strptime(time_slot_start, '%H:%M:%S').strftime('%H:%M')
                end_time_parsed = datetime.datetime.strptime(time_slot_end, '%H:%M:%S').strftime('%H:%M')
                time_slot = f"{start_time_parsed} - {end_time_parsed}"
            except ValueError:
                time_slot = f"{time_slot_start} - {time_slot_end}"
                print(f"警告: 時間形式が予期せぬ形式です (HH:MM:SS以外): {time_slot_start}, {time_slot_end}")

            subject = row[3]
            teacher = row[2]
            status = row[6]

            is_in_session = False
            if status == '質問対応中': # <-- ここを '公開中' から '質問対応中' に変更
                is_in_session = True
                status_text = "質問対応中" # 表示するテキストも変更
            elif status == '可能':
                status_text = "可能"
            else:
                status_text = status # その他のステータスはそのまま

            # 「質問対応中」または「可能」なもののみを対象とする
            if is_in_session or status == '可能':
                data_item = {
                    "date": row_date.strftime('%Y/%m/%d'),
                    "weekday": weekday_jp,
                    "time_slot": time_slot,
                    "subject": subject,
                    "teacher": teacher,
                    "status": status_text, # 修正後のstatus_textを使用
                    "is_in_session": is_in_session # 新しいフラグ
                }
                if row_date_str not in grouped_data_by_date:
                    grouped_data_by_date[row_date_str] = []
                grouped_data_by_date[row_date_str].append(data_item)
        
        # 日付と時間帯でソート
        sorted_output = {}
        for date_str in sorted(grouped_data_by_date.keys()):
            # 各日付内のデータを時間帯でソート
            sorted_by_time = sorted(grouped_data_by_date[date_str], 
                                    key=lambda x: datetime.datetime.strptime(x['time_slot'].split(' - ')[0], '%H:%M').time())
            sorted_output[date_str] = sorted_by_time

        return sorted_output # 日付をキーとする辞書を返す

    except Exception as e:
        print(f"データ取得中にエラーが発生しました: {e}")
        return {} # 空の辞書を返す

# --- Flaskのルート設定 ---

# トップページ: 科目選択画面を表示
@app.route('/')
def index():
    return render_template('index.html')

# 科目詳細ページ: 特定の科目の対応状況を表示
@app.route('/subject/<sheet_name>')
def subject_detail_page(sheet_name):
    # subject_detail.html に sheet_name を渡してレンダリング
    return render_template('subject_detail.html', sheet_name=sheet_name)

# APIエンドポイント: スプレッドシート内の全シート名を取得
# app.py の api_sheets エンドポイント内

@app.route('/api/sheets')
def api_sheets():
    try:
        spreadsheet_metadata = sheets.get(spreadsheetId=SPREADSHEET_ID).execute()
        all_sheet_names = [sheet['properties']['title'] for sheet in spreadsheet_metadata.get('sheets', [])]
        
        # --- 修正箇所: 除外したいシート名に「勤務時間」「特訓時間」を追加 ---
        excluded_sheets = ["質問対応可能時間", "時間", "講師情報", "勤務時間", "特訓時間"] # 除外したいシート名
        subject_sheet_names = [name for name in all_sheet_names if name not in excluded_sheets]
        
        return jsonify(subject_sheet_names)
    except Exception as e:
        print(f"シート名取得中にエラーが発生しました: {e}")
        return jsonify([])

# APIエンドポイント: 指定されたシートの対応状況を取得 (以前と同じ)
@app.route('/api/availability_by_sheet/<sheet_name>')
def api_availability_by_sheet(sheet_name):
    range_name = f"{sheet_name}!A2:G" 
    data = get_formatted_availability_data(sheet_name, range_name, num_days=5) # num_days=5 を渡す
    return jsonify(data)

# --- アプリケーションの実行 ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
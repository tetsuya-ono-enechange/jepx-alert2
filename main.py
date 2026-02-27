import os
import pandas as pd
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

PRICE_LIMIT = 15.0
SUPER_CHEAP_LIMIT = 5.0
OUTPUT_FILE = "result.txt"

def save_report(text):
    print("=== 保存するレポート内容 ===")
    print(text)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"レポートを {OUTPUT_FILE} に保存しました！")

async def main_logic():
    print("処理を開始します...", flush=True)
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    correct_csv_path = None
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})
            page.set_default_timeout(30000)
            
            await page.goto("https://www.jepx.jp/electricpower/market-data/spot/")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

            try:
                cal_input = page.locator('input[placeholder*="日付"], .flatpickr-input').first
                await cal_input.click(timeout=5000)
                await page.wait_for_timeout(1000)
                day_cell = page.locator('.flatpickr-day:not(.prevMonthDay):not(.nextMonthDay)').last
                await day_cell.click(timeout=5000)
                await page.wait_for_timeout(1000)
            except Exception:
                pass 

            buttons = page.locator('button:has-text("ダウンロード"), a:has-text("ダウンロード")')
            count = await buttons.count()
            
            for i in range(count):
                button = buttons.nth(i)
                try:
                    async with page.expect_download(timeout=15000) as dl_info:
                        await button.evaluate("node => node.click()")
                    download = await dl_info.value
                    temp_path = f"jepx_candidate_{i}.csv"
                    await download.save_as(temp_path)
                    
                    try:
                        df_temp = pd.read_csv(temp_path, encoding="shift_jis")
                        cols = df_temp.columns.tolist()
                        if any("東京" in col for col in cols):
                            correct_csv_path = temp_path
                            break 
                    except Exception:
                        continue 
                except Exception:
                    continue 
            await browser.close()
    except Exception as e:
        save_report(f"【システムエラー】ブラウザ操作中にエラーが発生しました。\n詳細: {e}")
        return

    if not correct_csv_path:
        save_report("【エラー】本物のスポット市場データが見つかりませんでした。")
        return

    try:
        df = pd.read_csv(correct_csv_path, encoding="shift_jis")
        columns = df.columns.tolist()
        target_area = next((col for col in columns if "東京" in col and "プライス" in col), None)
        df = df.dropna(subset=["受渡日", target_area])
        
        tomorrow_str_padded = tomorrow.strftime("%Y/%m/%d")
        tomorrow_str_unpadded = f"{tomorrow.year}/{tomorrow.month}/{tomorrow.day}"
        df_target = df[(df["受渡日"] == tomorrow_str_padded) | (df["受渡日"] == tomorrow_str_unpadded)].copy()
        target_date_str = "明日"
        
        if df_target.empty:
            today_str_padded = now.strftime("%Y/%m/%d")
            today_str_unpadded = f"{now.year}/{now.month}/{now.day}"
            df_target = df[(df["受渡日"] == today_str_padded) | (df["受渡日"] == today_str_unpadded)].copy()
            target_date_str = "今日"
            if df_target.empty:
                save_report("【エラー】CSV内に今日・明日のデータがまだ反映されていません。")
                return

        df_target['時刻コード'] = pd.to_numeric(df_target['時刻コード'])
        min_row = df_target.loc[df_target[target_area].idxmin()]
        min_price = min_row[target_area]
        time_code = int(min_row['時刻コード'])
        hour = (time_code - 1) // 2
        minute = "30" if time_code % 2 == 0 else "00"

        cheap_count = len(df_target[df_target[target_area] <= PRICE_LIMIT])

        super_cheap_slots = df_target[df_target[target_area] <= SUPER_CHEAP_LIMIT]
        super_cheap_times = []
        for _, row in super_cheap_slots.iterrows():
            tc = int(row['時刻コード'])
            h = (tc - 1) // 2
            m = "30" if tc % 2 == 0 else "00"
            super_cheap_times.append(f"{h:02d}:{m}")
        super_cheap_str = "、".join(super_cheap_times) if super_cheap_times else "なし"

        daytime_mask = (df_target['時刻コード'] >= 17) & (df_target['時刻コード'] <= 36)
        daytime_avg = round(df_target.loc[daytime_mask, target_area].mean(), 2)
        nighttime_avg = round(df_target.loc[~daytime_mask, target_area].mean(), 2)

        if daytime_avg < nighttime_avg:
            recommend = "日中 (8時〜18時)"
        elif nighttime_avg < daytime_avg:
            recommend = "夜間 (18時〜翌8時)"
        else:
            recommend = "どちらも同じ"

        message = (
            f"【{target_date_str}のJEPX価格情報】\n"
            f"👑 最安値: {min_price}円 ({hour:02d}:{minute}〜)\n"
            f"🔋 {PRICE_LIMIT}円以下のコマ数: {cheap_count}コマ\n"
            f"✨ {SUPER_CHEAP_LIMIT}円以下の時間帯:\n"
            f"{super_cheap_str}\n\n"
            f"📊 平均単価比較\n"
            f"☀️ 日中(8-18時): {daytime_avg}円\n"
            f"🌙 夜間(18-翌8時): {nighttime_avg}円\n\n"
            f"💡 全体的に【{recommend}】の方が安いです！"
        )
        save_report(message)
    except Exception as e:
        save_report(f"【エラー】CSV解析中にエラーが発生しました。\n詳細: {e}")

if __name__ == "__main__":
    asyncio.run(main_logic())

# youtube_spot_diff

間違い探し動画（opening -> Q1 -> Q2 -> Q3 -> ending）を自動生成し、必要ならYouTubeへアップロードする最小構成です。

## できること
- opening.mp4 を再生
- メインパート開始と同時に `main_bgm.mp3` を最後まで再生
- 各Qで `questionN.mp4` 再生後、`S1..S11.mp4` から重複なしランダム背景をループ
- 背景開始0.5秒後に左右画像をスライドイン（930x780 / x=20,970）
- 90秒カウントダウン
- `description.mp3` / 残60秒 `60s.mp3` / 残30秒 `30s.mp3`
- 残10秒で `count10.mp4` を右上表示
- 0秒で `alarm.mp4` を最上位表示
- その後 `answer.mp3` -> `answer1.mp3` -> `answer2.mp3` -> `answer3.mp3`
- 差分座標JSONに基づいて青/黄/赤の丸を順番表示

## 前提
- Python 3.11+
- ffmpeg

## セットアップ
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## ダミー素材で試す
```bash
python scripts/generate_dummy_assets.py
mkdir -p assets/input
cp -r assets/dummy/* assets/input/
python scripts/run_pipeline.py --job config/dummy_job.json --assets assets/input --output out/spot_diff.mp4
```

## S3素材を使う
```bash
python scripts/download_assets.py --bucket <your-bucket> --prefix <your-prefix> --dest assets/input
python scripts/run_pipeline.py --job config/dummy_job.json --assets assets/input --output out/spot_diff.mp4
```

## YouTubeアップロード
環境変数を設定して `--upload` を付けます。

```bash
export YOUTUBE_TOKEN_JSON='...'
export YOUTUBE_CLIENT_SECRETS_JSON='...'
python scripts/run_pipeline.py \
  --job config/dummy_job.json \
  --assets assets/input \
  --output out/spot_diff.mp4 \
  --upload \
  --title "脳トレ間違い探し Vol.1" \
  --description "自動生成テスト"
```

## Lambda連携時の差分JSON
将来、Lambdaから受ける差分情報は `config/dummy_job.json` の `diff_points` 形式に揃えてください。

```json
{
  "left_x": 270,
  "left_y": 380,
  "right_x": 1250,
  "right_y": 400,
  "radius": 38
}
```

`left_x,left_y,right_x,right_y` は最終動画キャンバス(1920x1080)座標です。

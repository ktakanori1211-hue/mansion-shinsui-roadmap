# 提出フォームに貼る文（Built with Claude: Japan 2026）

提出先：https://cerebralvalley.ai/e/built-with-claude-japan2026/hackathon/submit （ログインが要るので、本人がフォームを開いて貼る）。締切 2026-11-08（日）20:00 JST。
フォームの項目名は開いてみるまで分からないので、よくある項目ごとに文を置く。字数の枠に合わせて [docs/OVERVIEW.md](OVERVIEW.md) の短い版・標準版・詳細版と組み合わせる。数字は「根拠と資料」とサーバーの表の出典のまま。

## 1. 作品名（Project name）

- 日本語：マンション浸水チェック
- English: Mansion Shinsui Check — flood-readiness check for condominium boards

## 2. 一言（Tagline, 100字前後）

- 日本語：ハザードマップに色がないマンションでも、地下の機械室が浸かれば全戸で水・トイレ・エレベーターが止まる。住所と竣工図から止まる設備と対策を読み、理事会に出すA4一枚にする。
- English: Even where the hazard map shows no color, a flooded basement machine room stops water, toilets and elevators for every unit. From an address and the as-built drawings, it finds what stops, what to do first, and puts it on one A4 page for the board.

## 3. 説明（Description）

字数の枠が 500 字前後なら OVERVIEW の標準版、1,000 字以上なら詳細版をそのまま貼る。英語の枠があれば次の要約。

**English (about 180 words).** In Japan's August–September 2026 storms, 64% of the 447 flood and road-inundation reports in Chiba Prefecture (Typhoon 25, Weathernews 2026-09-22) were in places with no color on the flood hazard map. For a condominium, the real loss is not the power outage but what follows: when the basement or ground-floor electrical room or water-pump room floods, every unit loses water, toilets and elevators for days (8 days without water and 11 without toilets in a 2019 Kawasaki case). The path water takes into the electrical room (cable conduits, low vents, floor-mounted panels) falls between the building manager and the electrical safety contractor.

Mansion Shinsui Check takes an address, multiplies the national hazard maps by terrain data (GSI landform classification, elevation, inland-flood data) to flag "no color on the map, but a flood-prone landform", reads the as-built drawings with Claude to locate the pump room, electrical room and utility room, animates how water enters and what stops on CAD-style plans and sections, and produces a one-page A4 for the board: what it costs if nothing is done, what prevention costs per unit, and what to decide today. Judgments are rule-based; Claude only reads, searches and explains, and dangerous questions never reach the AI.

## 4. Claude の使い方（How you used Claude / Claude Code）

**作り方**：設計からコード、テスト、見本の図面の作図、公開前の安全点検まで Claude Code で作った（Python 3.9 の標準ライブラリと素の JavaScript・SVG だけ。外部ライブラリなし。テスト 452 件）。要件の決定は docs/REQUIREMENTS.md に 24 回分を番号つきで残し、画面の文字量はテストで上限を見張る。

**アプリの中の Claude（claude-opus-5-5）**：
- 竣工図の読み取り（Vision）：平面図・断面図・電気設備図・給排水設備図を複数枚まとめて読み、給水ポンプ室・電気室・借室の階、階数、引込み（地中／架空）、受電（高圧／低圧）、盤の置き方、排水の放流先を候補にして、答えに自動で入れる（取り消せる）。
- Web 検索：住所または建物名から、建物名・階数・戸数・築年を出典つきで探し、押させずに反映する。
- チャット：建物の情報・判定・出典を読んで答え、平面図の部屋を光らせる・水位や対策を切り替えるといった画面の操作を返す。
- 相談文の下書き：現地調査・見積もり仕様カルテ、管理会社・工事業者への依頼文、補助の手続きの順番。

**安全の設計**：判定はプログラムの規則だけで、Claude には変えさせない。分からないことは「未確認」で、危険とも安全とも言わない。浸水した電気室への立入や復電などの危ない質問は AI を通さず 0 秒で安全基準の案内（実機で 20 問すべて）。Claude の文は数字・禁止の語・留保・確かめる主語を事後に検査し、通らなければ定型に戻す。図面は Files API に上げず、その都度の要求に入れる。応答はキャッシュし、同じ入力では API を呼ばない。

## 5. 独自性・だれが作ったか（What makes it unique）

作者は電気主任技術者。浸水した建物の現場に立ち会い、受電設備は無事でも一番低い階の給水ポンプ制御盤が浅い水につかっただけで断水した例を見てきた。点検から抜けやすい「水の入り道」を、理事が管理会社に頼める問いと、理事会で決められる安い対策（止水板・壁の穴埋め、5 万〜180 万円）に変え、その場で動ける 1 枚に着地させる。出発点は「ひとりが深い知見から紡ぎ出すもの」。

## 6. 技術（Tech stack）

Python 3.9 標準ライブラリのサーバー（http.server）、素の JavaScript と SVG の画面、建築 CAD 風の平面図・断面図を描く自前の描画（web/cad.js、DXF も出力）、Anthropic Messages API（Vision・Web 検索ツール・JSON スキーマ・プロンプトキャッシュ）、国土地理院（住所検索・標高・地形分類）、ハザードマップポータル、zipcloud、OpenStreetMap Nominatim。追加のインストールなしで `python3 -m app.server`。

## 7. リンク（Links）

- リポジトリ（public）：https://github.com/ktakanori1211-hue/mansion-shinsui-roadmap
- デモ動画：（2026-11-08 に撮る。3 分以内・日本語・動く様子が中心。URL が決まったら README の「デモ動画」の行にも入れる）
- 動作 URL：なし（手元で起動する。提出要件に必須とは確認できていない）

## 8. チーム（Team）

1 名（作者）。GitHub：ktakanori1211-hue。

## 9. 期間中の開発分（Scope）

リポジトリのコードと README・docs はすべて 2026-11-02〜11-08 の期間中に書いた（初コミット 2026-11-02）。見本の建物・図面・点検報告書は期間中に `scripts/draw_plans.py` で新しく作った架空のもので、実在の建物の図面や記録は含まない。

## 10. 出す前の確認

- [ ] README のデモ動画の行に URL を入れて push した
- [ ] 動画を最初から最後まで見返した（有効な API キー・他人の実データ・エラー画面の機密が映っていない）
- [ ] GitHub の Settings：public、共同編集者なし、Secret scanning と Push protection が有効
- [ ] フォームの各欄を、上の文と OVERVIEW の版から字数に合わせて貼った

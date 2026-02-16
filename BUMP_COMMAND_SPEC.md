# Bumpコマンド仕様書

## 概要

`%bump`コマンドは、DISBOARD等のDiscordサーバーリストサービスと連携し、ユーザーが指定したランダムなインターバルで**永続的に** `/bump` コマンドをチャンネルに送信し続ける機能です。

一度実行すると、`%bumpcancel` で停止するかBotが再起動するまで、繰り返し自動送信されます。

---

## コマンド仕様

### `%bump random(<最小秒>, <最大秒>)`

**説明**: 指定した範囲のランダムなインターバルで、`/bump` を**繰り返し**チャンネルに送信し続けます

**書式**:

```
%bump random(<最小秒>, <最大秒>)
```

**使用例**:

```
%bump random(7200, 9000)
%bump random(3600, 7200)
%bump random(120, 300)
```

**パラメータ**:
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| 最小秒 | int | インターバルの最小値（秒） |
| 最大秒 | int | インターバルの最大値（秒） |

**制約**:

- `最小秒 > 0` であること
- `最小秒 <= 最大秒` であること
- 同一チャンネルで複数のbumpタスクは実行不可（既存タスクを上書き）

---

## 動作フロー

```
1. ユーザーが %bump random(7200, 9000) を実行
2. Botが受け付けた旨を返信（インターバル範囲を表示）
3. random(7200, 9000) の範囲でランダムな待機時間を生成
4. 待機時間後、チャンネルに /bump を送信
5. 再びランダムな待機時間を生成 → 手順3に戻る
   （%bumpcancel されるまで無限に繰り返す）
```

```
[%bump random(7200,9000)]
         │
         ▼
    ┌─────────────┐
    │ 開始メッセージ │
    │ を送信        │
    └──────┬──────┘
           │
           ▼
    ┌─────────────────────┐
    │ wait = random(7200, │◄────────┐
    │         9000)       │         │
    └──────┬──────────────┘         │
           │                        │
           ▼                        │
    ┌─────────────┐                 │
    │ asyncio     │                 │
    │ .sleep(wait)│                 │
    └──────┬──────┘                 │
           │                        │
           ▼                        │
    ┌─────────────┐                 │
    │ /bump を    │                 │
    │ チャンネルに │                │
    │ 送信        │                 │
    └──────┬──────┘                 │
           │                        │
           └────────────────────────┘
                  (ループ)

    ※ %bumpcancel で停止
```

---

## 具体例: `%bump random(7200, 9000)` の挙動

`7200` = 2時間、`9000` = 2時間30分

### 時系列

```
[10:00:00] ユーザーが %bump random(7200, 9000) を送信
[10:00:00] Bot → 「🔔 Bump自動送信を開始します
                   ⏰ インターバル: 7200秒 〜 9000秒
                   🔁 停止するまで繰り返し /bump を送信します
                   🛑 停止: %bumpcancel」

           ── 1回目: random(7200,9000) → 7523秒(≒2時間5分) を待機 ──

[12:05:23] Bot → /bump    ← 1回目のbump

           ── 2回目: random(7200,9000) → 8401秒(≒2時間20分) を待機 ──

[14:25:24] Bot → /bump    ← 2回目のbump

           ── 3回目: random(7200,9000) → 7200秒(≒2時間ちょうど) を待機 ──

[16:25:24] Bot → /bump    ← 3回目のbump

           ── 4回目: random(7200,9000) → 8899秒(≒2時間28分) を待機 ──

[18:53:23] Bot → /bump    ← 4回目のbump

           … 以降、%bumpcancel が実行されるまで永遠に繰り返し …
```

### ポイント

| 項目                       | 内容                                                     |
| -------------------------- | -------------------------------------------------------- |
| **インターバル範囲**       | 毎回 7200秒（2時間）〜 9000秒（2時間30分）の間でランダム |
| **ランダム生成タイミング** | `/bump` を送信した**直後**に次の待機時間を決定           |
| **送信内容**               | `/bump` というテキストメッセージ                         |
| **送信先**                 | `%bump` を実行したチャンネルと同じチャンネル             |
| **繰り返し**               | 無限ループ（`%bumpcancel` で停止）                       |
| **間隔のばらつき**         | 毎回独立にランダム値を生成するため、間隔は毎回異なる     |

### なぜ 7200〜9000 か

- DISBOARDのbumpクールダウンは **2時間（7200秒）**
- 最小値を7200にすることでクールダウン明けにbumpできる
- 最大値を9000にすることで、多少の遅延幅を持たせて自然なタイミングにする
- 2時間ちょうどに固定すると機械的すぎるため、ランダム化で分散させる

---

## 実装仕様

### インターバル計算

毎回のループで新しいランダム値を生成します：

```python
wait_time = random.randint(min_interval, max_interval)
```

### 引数のパース

`random(min, max)` 形式の文字列から最小値・最大値を抽出します：

```python
# "random(7200, 9000)" → min_interval=7200, max_interval=9000
match = re.match(r'random\(\s*(\d+)\s*,\s*(\d+)\s*\)', arg)
min_interval = int(match.group(1))
max_interval = int(match.group(2))
```

---

## コマンド実装コード

```python
@commands.command()
async def bump(self, ctx, *, arg):
    """
    ランダムなインターバルで /bump コマンドを繰り返し送信します
    使用例: %bump random(7200, 9000)
    """
    # 引数をパース
    match = re.match(r'random\(\s*(\d+)\s*,\s*(\d+)\s*\)', arg)
    if not match:
        await ctx.send(
            '❎ 書式が正しくありません\n'
            '使用例: `%bump random(7200, 9000)`'
        )
        return

    min_interval = int(match.group(1))
    max_interval = int(match.group(2))

    # バリデーション
    if min_interval <= 0:
        await ctx.send('❎ 最小値は1以上を指定してください')
        return
    if min_interval > max_interval:
        await ctx.send('❎ 最小値が最大値を超えています')
        return

    # 既存タスクがあればキャンセル
    if not hasattr(self, 'bump_tasks'):
        self.bump_tasks = {}

    task_id = f"{ctx.guild.id}_{ctx.channel.id}"
    if task_id in self.bump_tasks:
        self.bump_tasks[task_id]['task'].cancel()

    # 開始メッセージを送信
    await ctx.send(
        f'🔔 Bump自動送信を開始します\n'
        f'⏰ インターバル: {min_interval}秒 〜 {max_interval}秒\n'
        f'🔁 停止するまで繰り返し /bump を送信します\n'
        f'🛑 停止: `%bumpcancel`'
    )

    # 無限ループの非同期タスク
    async def bump_loop():
        count = 0
        try:
            while True:
                # 毎回ランダムな待機時間を生成
                wait_seconds = random.randint(min_interval, max_interval)
                next_time = datetime.datetime.now() + datetime.timedelta(seconds=wait_seconds)

                # タスク情報を更新（次回送信時刻）
                self.bump_tasks[task_id]['next_bump'] = next_time
                self.bump_tasks[task_id]['count'] = count

                # 待機
                await asyncio.sleep(wait_seconds)

                # /bump を送信
                await ctx.channel.send('/bump')
                count += 1

        except asyncio.CancelledError:
            # キャンセル時は静かに終了
            pass
        except Exception as e:
            await ctx.channel.send(
                f'❌ Bump自動送信中にエラーが発生しました: {e}\n'
                f'🔁 送信回数: {count}回'
            )

    # タスク開始
    task = self.loop.create_task(bump_loop())

    self.bump_tasks[task_id] = {
        'task': task,
        'min_interval': min_interval,
        'max_interval': max_interval,
        'channel_id': ctx.channel.id,
        'author_id': ctx.author.id,
        'started_at': datetime.datetime.now(),
        'next_bump': datetime.datetime.now() + datetime.timedelta(
            seconds=random.randint(min_interval, max_interval)
        ),
        'count': 0
    }
```

---

## 補助コマンド

### `%bumpstatus`

**説明**: 現在実行中のbump自動送信の状態を表示します

**実装例**:

```python
@commands.command()
async def bumpstatus(self, ctx):
    """
    実行中のbump自動送信の状態を表示します
    """
    if not hasattr(self, 'bump_tasks') or len(self.bump_tasks) == 0:
        await ctx.send('⚠️ 実行中のbumpタスクはありません')
        return

    task_id = f"{ctx.guild.id}_{ctx.channel.id}"

    if task_id not in self.bump_tasks:
        await ctx.send('⚠️ このチャンネルで実行中のbumpタスクはありません')
        return

    info = self.bump_tasks[task_id]
    next_bump = info.get('next_bump')
    remaining = (next_bump - datetime.datetime.now()).total_seconds()

    if remaining > 0:
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        seconds = int(remaining % 60)
        remaining_str = f'{hours}時間 {minutes}分 {seconds}秒'
    else:
        remaining_str = 'まもなく送信...'

    await ctx.send(
        f'🔁 Bump自動送信 実行中\n'
        f'⏰ インターバル: {info["min_interval"]}秒 〜 {info["max_interval"]}秒\n'
        f'📅 次回送信: {next_bump.strftime("%Y-%m-%d %H:%M:%S")}\n'
        f'⏱️ 残り時間: {remaining_str}\n'
        f'📊 送信回数: {info.get("count", 0)}回\n'
        f'🕐 開始時刻: {info["started_at"].strftime("%Y-%m-%d %H:%M:%S")}'
    )
```

---

### `%bumpcancel`

**説明**: 実行中のbump自動送信を停止します

**実装例**:

```python
@commands.command()
async def bumpcancel(self, ctx):
    """
    実行中のbump自動送信を停止します
    """
    if not hasattr(self, 'bump_tasks') or len(self.bump_tasks) == 0:
        await ctx.send('⚠️ 停止できるbumpタスクがありません')
        return

    task_id = f"{ctx.guild.id}_{ctx.channel.id}"

    if task_id not in self.bump_tasks:
        await ctx.send('⚠️ このチャンネルで実行中のbumpタスクはありません')
        return

    info = self.bump_tasks[task_id]
    count = info.get('count', 0)
    started_at = info['started_at'].strftime('%Y-%m-%d %H:%M:%S')

    # タスクをキャンセル
    info['task'].cancel()
    del self.bump_tasks[task_id]

    await ctx.send(
        f'🛑 Bump自動送信を停止しました\n'
        f'📊 送信回数: {count}回\n'
        f'🕐 稼働開始: {started_at}'
    )
```

---

## 使用シナリオ

### 基本的な使い方

1. **Bump自動送信の開始**

   ```
   ユーザー: %bump random(7200, 9000)
   Bot: 🔔 Bump自動送信を開始します
        ⏰ インターバル: 7200秒 〜 9000秒
        🔁 停止するまで繰り返し /bump を送信します
        🛑 停止: %bumpcancel
   ```

2. **約2時間〜2時間30分後（1回目）**

   ```
   Bot: /bump
   ```

3. **さらに約2時間〜2時間30分後（2回目）**

   ```
   Bot: /bump
   ```

4. **（以降、停止するまで繰り返し）**

5. **ステータス確認**

   ```
   ユーザー: %bumpstatus
   Bot: 🔁 Bump自動送信 実行中
        ⏰ インターバル: 7200秒 〜 9000秒
        📅 次回送信: 2026-02-16 17:45:32
        ⏱️ 残り時間: 1時間 23分 10秒
        📊 送信回数: 3回
        🕐 開始時刻: 2026-02-16 10:00:00
   ```

6. **停止**
   ```
   ユーザー: %bumpcancel
   Bot: 🛑 Bump自動送信を停止しました
        📊 送信回数: 5回
        🕐 稼働開始: 2026-02-16 10:00:00
   ```

### よくある設定例

| 用途         | コマンド                   | 説明              |
| ------------ | -------------------------- | ----------------- |
| DISBOARD標準 | `%bump random(7200, 9000)` | 2〜2.5時間間隔    |
| 短めの間隔   | `%bump random(7200, 7500)` | ほぼ2時間ぴったり |
| テスト用     | `%bump random(60, 120)`    | 1〜2分間隔        |

---

## エラーハンドリング

### 入力エラー

| パターン                   | エラーメッセージ                   |
| -------------------------- | ---------------------------------- |
| `%bump` (引数なし)         | ❎ 書式が正しくありません          |
| `%bump random(abc, 100)`   | ❎ 書式が正しくありません          |
| `%bump random(0, 100)`     | ❎ 最小値は1以上を指定してください |
| `%bump random(9000, 7200)` | ❎ 最小値が最大値を超えています    |

### 実行時エラー

| エラーケース           | 動作                                       |
| ---------------------- | ------------------------------------------ |
| チャンネルが削除された | タスクが自動終了                           |
| Botに送信権限がない    | エラー通知を試み、タスク終了               |
| Bot再起動              | 実行中のタスクは消失                       |
| 同じチャンネルで再実行 | 既存タスクをキャンセルし、新しい設定で再開 |

---

## パフォーマンス考慮事項

1. **メモリ使用量**: `asyncio.sleep()` 中はほぼメモリを消費しない
2. **タスク数**: サーバー×チャンネルごとに最大1タスク
3. **推奨**: 1サーバーあたり1チャンネルでの使用を推奨

---

## セキュリティ考慮事項

1. **最小インターバル制限**: 極端に短い間隔でのスパムを防ぐため、最小値に下限を設けることを推奨（例: 60秒以上）
2. **権限チェック**: 必要に応じて特定ロールのみ実行可能にする
3. **重複防止**: 同一チャンネルで1つのタスクのみ許可

---

## 権限要件

- **Bot権限**:
  - メッセージの送信
  - メッセージ履歴の閲覧
- **ユーザー権限**:
  - `%bump`: 全ユーザー（またはロール制限）
  - `%bumpcancel`: 実行者または管理者
  - `%bumpstatus`: 全ユーザー

---

## FAQ

**Q: なぜランダムな時間を使うのですか？**  
A: DISBOARDは2時間に1回のbumpが可能です。完全に固定の間隔ではなくランダムにすることで、自然なタイミングで送信されます。

**Q: 一度実行したら自分で止める必要がありますか？**  
A: はい。`%bumpcancel` を実行するかBotが再起動するまで永続的に繰り返します。

**Q: 同じチャンネルで2回実行するとどうなりますか？**  
A: 既存のタスクが自動的にキャンセルされ、新しい設定で再開されます。

**Q: Bot再起動後もタスクは維持されますか？**  
A: いいえ。再起動後は再度 `%bump` を実行する必要があります。

**Q: 複数のチャンネルで同時に実行できますか？**  
A: はい。チャンネルごとに独立したタスクとして動作します。

---

## 更新履歴

| バージョン | 日付       | 変更内容                                          |
| ---------- | ---------- | ------------------------------------------------- |
| 1.0.0      | 2026-02-16 | 初版リリース                                      |
| 2.0.0      | 2026-02-16 | `random(min, max)` 引数対応、無限ループ方式に変更 |

---

## ライセンス

このコマンドはBotのメインライセンス（WTFPL）に従います。

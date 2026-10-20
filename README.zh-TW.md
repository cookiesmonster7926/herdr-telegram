# herdr-telegram

在 [herdr](https://herdr.dev) 裡跑的 coding agent 停下來等你的時候，傳一則 Telegram 訊息給你；
在手機上按一下就能回答它。

[English](README.md)

## 它做什麼

- herdr 裡的 agent 進入 **blocked**（等你批准指令，或 Claude Code 用 `AskUserQuestion` 問你問題）時，
  你會收到一則 Telegram 訊息，內容是那個對話框：問題、選項、它想跑的指令。
- **每個選項都是一顆按鈕**，按下去就會在那個 agent 的畫面上按對應的鍵。
- **一次問好幾題、複選題、最後的確認頁**都能處理：你每按一下，同一則訊息就地更新（框打勾、換下一題），
  直到送出。
- **對訊息按「回覆」打字**，就是回答「Type something」。
- 安全措施：
  - 只接受你自己的 chat；
  - agent 畫面上還是同一個對話框時才會送鍵；
  - 會永久放寬權限的選項（don't ask again、always allow）永遠不會變成按鈕。

按鈕是照 Claude Code 的對話框做的（測過 Claude Code 2.1.304、herdr 0.9.3）。
其他 agent 一樣會收到通知與畫面文字，只是沒有按鈕。

## 需要什麼

- macOS，裝好 [herdr](https://herdr.dev) 0.9 以上
- [uv](https://docs.astral.sh/uv/)（用來跑接收按鈕的小程式）
- `jq` 與 `curl`（新版 macOS 內建；沒有的話 `brew install jq`）
- 一個 Telegram 帳號

## 安裝（macOS）

```sh
git clone https://github.com/cookiesmonster7926/herdr-telegram.git ~/herdr-telegram
cd ~/herdr-telegram
./install.sh
```

腳本只會問兩件事：

1. **bot token**：在 Telegram 打開 [@BotFather](https://t.me/BotFather)，傳 `/newbot`，照它的步驟做完，
   把它給你的 token 貼進來。
2. **對你的 bot 傳一則訊息**：打開剛建好的 bot，按 **Start**，再回到終端機按 Enter。
   腳本靠這一步找到你的 chat id。

接著它會把 plugin 接上 herdr，把設定存在 repo 外面（`herdr plugin config-dir herdr-telegram`，
只有你讀得到），在背景啟動接收按鈕的程式（開機登入也會自動啟動），最後傳一則測試訊息給你。這樣就好了。

- **更新**：`git pull && ./install.sh`
- **移除**：`./install.sh --uninstall`（設定會保留）
- 資料夾不要搬走：背景程式就是從這裡跑的。

## 語言

訊息可以是**英文**或**繁體中文**，`install.sh` 會問（直接按 Enter 是英文）。之後要改，就在
`herdr plugin config-dir herdr-telegram` 那個資料夾的 `language` 檔寫 `en` 或 `zh-TW`，再跑一次 `./install.sh`。

翻譯的只有 herdr-telegram 自己加上去的字：標題（「等你回答：」）、「這題選好了 →」按鈕、「已送出答案」這類提示。
問題、選項、指令一律照 agent 寫的原文顯示，它用什麼語言問就是什麼語言；Claude Code 自己畫的字
（「Submit answers」「Yes」「Type something」）也維持原樣。所以設成中文、Claude 用英文問的時候，
你會看到中文標題底下接英文問題。

## Windows（選用）

Windows 上也能發通知（PowerShell 5.1）。按鈕則由 Mac 上的背景程式透過 herdr 的遠端機器功能回答。

1. clone 並接上 herdr：
   ```powershell
   git clone https://github.com/cookiesmonster7926/herdr-telegram.git $env:USERPROFILE\herdr-telegram
   herdr plugin link $env:USERPROFILE\herdr-telegram
   ```
2. 在 `herdr plugin config-dir herdr-telegram` 印出的資料夾裡建一個叫 `telegram` 的檔（用跟 Mac 同一個 bot）：
   ```
   <bot token>
   <chat id>
   <選填：訊息底部顯示的名稱，例如 實驗室電腦>
   <選填：這台機器的代號，一個英文小寫字母，預設 w>
   ```
   chat id 就是 Mac 上同一個檔的第 2 行。要中文訊息的話，同一個資料夾再建一個 `language` 檔，內容寫 `zh-TW`。
   兩台機器可以設不同語言。
3. 在 Mac 上確認 `herdr --machine <名稱> agent list` 連得到那台（見 `herdr machine add`）。
   然後在 Mac 的 `herdr plugin config-dir herdr-telegram` 裡的 `machines` 檔加一行：
   ```
   w <herdr 裡那台機器的名稱>
   ```
   再在 Mac 上跑一次 `./install.sh`。

## 怎麼運作

```
agent 進入 blocked
  └─ 那台機器的 herdr 執行 plugin（macOS 跑 notify.sh，Windows 跑 notify.ps1）
       └─ 讀畫面 → 整理對話框 → 發 Telegram 訊息（附按鈕）
你按按鈕或回覆
  └─ Mac 上的背景程式（launchd）收到
       └─ 重讀那個 agent 的畫面：還在等、還是同一個對話框、選項可以按 → 送按鍵
          （其他機器上的 agent 透過 herdr --machine 操作）
       └─ 還在問（下一題、框打勾）→ 就地重畫同一則訊息
          問完了 → 標「已回答」並拿掉按鈕
```

## 注意事項

- Telegram 一個 bot 只能有一個程式在收訊息，所以背景程式**只裝在一台 Mac**。
- 那台 Mac 睡眠時通知照樣會到，但按鈕沒人接。
- 複選題的打字欄位只能從手機打一次；要改請到電腦上改。
- 按鈕依賴 Claude Code 畫對話框的方式。新版改了畫面時，可以用 `tests/capture.py` 錄新的畫面來更新測試。
- 看背景程式：`tail ~/Library/Logs/herdr-telegram.log`（記按鈕，不記你打的字）。
- 看 plugin 有沒有跑：`herdr plugin log list`。

## 開發

```sh
sh tests/run.sh                                    # 用錄下來的畫面測 dialog.awk
sh tests/install_test.sh                           # 用替身走一次首次安裝，不碰任何真的東西
cd listener && uv run --no-project --with pytest pytest -q
python3 tests/mutate.py                            # 一次改壞一條規則，每一條都要被測試抓到
sh tests/desktop.sh <ssh 主機>                      # 同一批畫面在 Windows 上跑 dialog.ps1
uv run tests/capture.py --help                     # 在獨立的 pty 錄 Claude Code 的真實畫面
```

`dialog.awk`（macOS）和 `dialog.ps1`（Windows）是同一個排版器的兩份實作，輸出必須逐字相同，
因為按鈕帶著它的指紋。兩個 `.ps1` 要存成 UTF-8 with BOM，否則 PowerShell 5.1 會用系統字碼頁讀。

## 授權

[MIT](LICENSE)

# Granola Local Export

Export your [Granola](https://granola.ai) meeting notes **and transcripts** to plain Markdown files on your own disk. It works with a **free Granola account** and needs no Granola API access.

Granola's official API and integrations are limited to paid plans. The Granola desktop app already keeps an encrypted copy of your meetings on your machine, though. This tool decrypts that local cache with your own Windows user credentials and writes one tidy `.md` file per meeting. You can then search the files, back them up, sync them, or give them to other tools (Obsidian, an LLM, grep, and so on).

## What you get

One file per meeting, named `YYYY-MM-DD - <Meeting title>.md`, containing:

- **Date, attendees, and the Granola ID** (used to avoid duplicates)
- **Granola AI Notes**: the AI summary panels
- **My Notes**: whatever you typed into the note during the meeting
- **Transcript**: speaker-labelled, with `[hh:mm:ss]` offsets (when Granola cached it on this device)

Other features:

- **Idempotent.** Meetings already exported are skipped. If a meeting was exported before its transcript or AI notes were ready, its file is upgraded in place on the next run.
- **Read-only.** It copies Granola's database to a temp folder before reading it, so the Granola app is never touched.
- **Runs your way.** Run it on demand after a meeting, or let Windows Task Scheduler run it daily.

## Requirements

- **Windows 10/11.** Decryption uses Windows DPAPI, so it must run as the same Windows user that runs Granola.
- **Granola desktop app**, installed and signed in (a free account works)
- **Python 3.9+** on your `PATH`

## Setup

1. **Get the code**

   ```powershell
   git clone https://github.com/ubshreenath/granola-export.git
   cd granola-export
   ```

2. **Install dependencies**

   ```powershell
   pip install -r requirements.txt
   ```

   (`sqlcipher3-wheels` provides prebuilt SQLCipher binaries for Windows, so you don't need a compiler.)

3. **Choose where your notes go.** By default, notes go to `%USERPROFILE%\Documents\Granola Notes`, which is created automatically. To use a different folder, replace the placeholder `<YOUR_OUTPUT_FOLDER>` in the commands below with your own path (for example `D:\Notes\Meetings`). You can set the folder in either of these ways:
   - pass `--out "<YOUR_OUTPUT_FOLDER>"` on each run, or
   - set it once as a user environment variable:

     ```powershell
     setx GRANOLA_EXPORT_OUT "<YOUR_OUTPUT_FOLDER>"
     ```

     (Open a new terminal afterwards so the variable is picked up.)

4. **Test it once**

   ```powershell
   python export_granola.py
   ```

   You should see lines like `NEW     2026-10-07 - Weekly sync.md [transcript]`, then a summary: `done: 3 new, 0 updated, 0 unchanged`.

## Usage

### On demand, after a meeting

Once Granola has finished generating the notes for a meeting, do one of the following:

- **Double-click `export_now.bat`**. A window shows what was exported and waits for a key press.
- Or run it from a terminal:

  ```powershell
  python export_granola.py --out "<YOUR_OUTPUT_FOLDER>"
  ```

You can safely run it as often as you like. Only new or upgraded meetings are written.

> Tip: Pin `export_now.bat` to Start, or create a desktop shortcut to it, for a one-click export after each call.

### Automatically, every day (Windows Task Scheduler)

`register_task.ps1` creates a scheduled task that runs the exporter silently (with `pythonw.exe`, so no console window opens) as your user.

Open PowerShell **in this folder** and run:

```powershell
# Default: every day at 11:00 PM, notes go to the default output folder
powershell -ExecutionPolicy Bypass -File .\register_task.ps1

# Custom time and output folder
powershell -ExecutionPolicy Bypass -File .\register_task.ps1 -At '6:30PM' -OutDir '<YOUR_OUTPUT_FOLDER>'
```

| Parameter   | Default                | Meaning                                   |
|-------------|------------------------|-------------------------------------------|
| `-At`       | `11:00PM`              | Time of day to run                        |
| `-OutDir`   | *(script default)*     | Folder to write the Markdown files to     |
| `-TaskName` | `Granola Daily Export` | Name shown in Task Scheduler              |

The task is configured to:

- run as soon as possible if the PC was off or asleep at the scheduled time (`StartWhenAvailable`)
- wake the PC to run, and run on battery power
- stop after 30 minutes if something hangs

**Manage the task:**

```powershell
Start-ScheduledTask   -TaskName 'Granola Daily Export'   # run it now
Get-ScheduledTaskInfo -TaskName 'Granola Daily Export'   # last run time / result
Unregister-ScheduledTask -TaskName 'Granola Daily Export' -Confirm:$false   # remove it
```

You can also open **Task Scheduler** (`taskschd.msc`) and find it under *Task Scheduler Library*.

> If you move this folder, re-run `register_task.ps1`. The task stores the script's full path.

## Command-line options

```
python export_granola.py [--out FOLDER] [--granola-dir FOLDER] [--tz +HH:MM]
```

| Option          | Default                                         | Description                                                        |
|-----------------|-------------------------------------------------|--------------------------------------------------------------------|
| `--out`         | `%GRANOLA_EXPORT_OUT%` or `~\Documents\Granola Notes` | Output folder for the Markdown files                       |
| `--granola-dir` | `%APPDATA%\Granola`                             | Granola's local data folder                                        |
| `--tz`          | system timezone                                 | Fixed UTC offset for dates and filenames, such as `+05:30` or `-08:00` |

## Logs and troubleshooting

- Each run appends to `export.log` in this folder.
- If a run fails, the full error is written to `LAST_ERROR.txt`. That file is removed after the next successful run.

| Symptom | Fix |
|---|---|
| `CryptUnprotectData failed` | Run the script as the **same Windows user** that uses Granola. If the task was registered as another account, re-register it. |
| `no cache-v*.json.enc found` / file not found | Make sure Granola is installed and has been opened at least once, or point `--granola-dir` at its data folder. |
| `ModuleNotFoundError: sqlcipher3` | `pip install -r requirements.txt` using the same Python the task runs (`(Get-Command python).Source`). |
| `Transcript not available locally` in a file | Granola didn't cache that transcript on this device. The file is upgraded automatically if the transcript shows up later. |
| `unexpected key format` / decryption errors after a Granola update | Granola may have changed its storage format. Please open an issue. |

## How it works

1. Reads the DPAPI-protected master key from `%APPDATA%\Granola\Local State` and unwraps it with your Windows credentials.
2. Uses that key to decrypt `storage.dek`, the data-encryption key.
3. Decrypts the local cache (`cache-v*.json.enc`, AES-GCM) to get transcripts.
4. Opens a **temporary copy** of the SQLCipher database `granola.db` to read documents, AI-note panels, attendees, and your own notes.
5. Converts Granola's rich-text JSON to Markdown and writes one file per meeting.

## Privacy and security

- Everything happens **locally**. Nothing is sent over the network.
- The decryption keys only work for your Windows user on your machine. The script cannot read someone else's Granola data.
- The exported files contain your full meeting content. Store and share them with the same care as the meetings themselves.
- `.gitignore` excludes `export.log`, `LAST_ERROR.txt`, exported `.md` files, and any Granola database or key files, so you don't commit meeting data by accident if you keep the output folder inside a clone.

## Disclaimer

This is an unofficial community tool. It is not affiliated with or endorsed by Granola. It reads an undocumented local storage format that may change with any Granola update. Use it only with your own data, and in line with Granola's terms and the consent rules that apply to your recordings.

## License

[MIT](LICENSE)

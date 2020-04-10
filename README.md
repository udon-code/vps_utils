# VPS管理用ツール


## `./scripts/backup_to_cloud.py`
* 差分バックアップ、クラウドストレージアップロード対応のバックアップツール

```
usage: backup_to_cloud.py [-h] -s path [-r <rclone path>] [-d folder] [-i]
                          [-P password] [-z] [--nocompress] [--mysql] [-n]
                          [-v] [-q] [--clean_local_after days] [--cleanall]
                          [--clean_remote_after days]

optional arguments:
  -h, --help            show this help message and exit
  -s path, --src path   Source folder(s). Can be specified multiple times
  -r <rclone path>, --remote <rclone path>
                        Remote path (<rclone remote name>:<remote folder>)
                        (ex. gdrive:backup)
  -d folder, --dst folder
                        Output folder, created a temporary one if omitted
  -i, --incremental     Backup differential from the latest full+diff backup.
                        (note: mySql backup doesnt support differential back)
  -P password, --password password
                        If specified, encrypt zip file with given password
  -z, --zip             Use zip instead of zip (default is 7z)
  --nocompress          Skip compression
  --mysql               Save mysql database (may require root privilege)
  -n, --noexec          dry run
  -v, --verbose         Verbose mode
  -q, --quiet           Quiet mode
  --clean_local_after days
                        Delete old backup files older than specified days(In
                        incremental mode, delete old *_diff after a full
                        backup before specified days)(In fullbackup mode,
                        delete old full backup before specified days)(Delete
                        compressed file when --remote presents)
  --cleanall            Delete everything but the latest archive
  --clean_remote_after days
                        Delete remote file older than specified days
```

### 必要パッケージ
* rsync
* python3.6 or later
* p7zip-full or zip (バックアップフォルダを圧縮する場合)
* rclone (バックアップアーカイブをクラウドストレージにアップロードする場合)

すべて`apt install`でインストールできると思います

### 使用例
#### 対象フォルダ(folder1, folder2)をローカルフォルダにフルバックアップ
```
% ./scripts/backup_to_cloud.py \
  -s folder1 -s folder2        \  # 対象フォルダ
  -d backup                    \  # バックアップフォルダ
  -P password                  \  # .7zを'password'で暗号化
  --clean_local_after 7        \  # 7日より前のバックアップを削除
```

#### 対象フォルダ(folder1, folder2)をローカルフォルダに差分バックアップ
```
% ./scripts/backup_to_cloud.py \
  -i                           \  # 差分バックアップ
  -s folder1 -s folder2        \  # 対象フォルダ
  -d backup                    \  # バックアップフォルダ (最新のフルバックフォルダとそれ以降の
                               \  # 差分バックアップフォルダを使用)
  -P password                  \  # .7zを'password'で暗号化
  --clean_local_after 7        \  # 7日より前の差分バックアップを削除
```

#### 対象フォルダ(folder1, folder2)をGoogle Driveにバックアップ
```
% ./scripts/backup_to_cloud.py \
  -s folder1 -s folder2        \  # 対象フォルダ
  -d backup                    \  # バックアップフォルダ
  -P password                  \  # .7zを'password'で暗号化
  --clean_local_after 1        \  # 1日より前のバックアップを削除
  -r gdrive:Backup             \  # リモートにアップロード (gdriveはrcloneで設定したリモートネーム)
  --clean_remote_after 7       \  # 7日より前のリモートファイルを削除
```

#!/usr/bin/python3
import argparse
from datetime import datetime, timedelta
import logging
import logging.config
import os
import re
import subprocess
import sys
import shutil
import tempfile

assert sys.version_info.major >= 3, "Support only Python 3.6 or later"
assert sys.version_info.minor >= 6, "Support only Python 3.6 or later"


class BackupUtils:

    @classmethod
    def add_options(cls, parser):
        parser.add_argument('-s', '--src',
                            help='Source folder(s). Can be specified multiple times',
                            default=[],
                            required=True,
                            action='append',
                            metavar='path')
        parser.add_argument('-r', '--remote',
                            help='Remote path (<rclone remote name>:<remote folder>)'
                            ' (ex. gdrive:backup)',
                            metavar='<rclone path>'
                            )
        parser.add_argument('-d', '--dst',
                            help='Output folder, created a temporary one if omitted',
                            metavar='folder')
        parser.add_argument('-i', '--incremental',
                            help='Backup differential from the latest full+diff backup.'
                            ' (note: mySql backup doesn''t support differential back)',
                            action='store_true')
        parser.add_argument('-P', '--password',
                            help='If specified, encrypt zip file with given password',
                            metavar='password')
        parser.add_argument('-z', '--zip',
                            help='Use zip instead of zip (default is 7z)',
                            action='store_true')
        parser.add_argument('--nocompress',
                            help='Skip compression',
                            action='store_true')
        parser.add_argument('--mysql',
                            help='Save mysql database (may require root privilege)',
                            action='store_true')
        parser.add_argument('-n', '--noexec',
                            help='dry run',
                            action='store_true')
        parser.add_argument('-v', '--verbose',
                            help='Verbose mode',
                            action='store_true')
        parser.add_argument('-q', '--quiet',
                            help='Quiet mode',
                            action='store_true')
        parser.add_argument('--clean_local_after',
                            help='Delete old backup files older than specified days'
                            '(In incremental mode, delete old *_diff after a full backup before specified days)'
                            '(In fullbackup mode, delete old full backup before specified days)'
                            '(Delete compressed file when --remote presents)',
                            type=int,
                            metavar='days')
        parser.add_argument('--cleanall',
                            help='Delete everything but the latest archive',
                            action='store_true')
        parser.add_argument('--clean_remote_after',
                            help='Delete remote file older than specified days',
                            type=int,
                            metavar='days')

    def __init__(self, args):
        self.logger = self.getLogger(logging.DEBUG)
        self.args = args
        if args.quiet:
            self.logger.setLevel(logging.WARNING)
        self.args.verbose = self.args.verbose or self.args.noexec

        self.error_flags = False
        self.dst = args.dst
        self.dst_root = args.dst
        self.src_list = args.src
        self.tempdir = None

        self.last_full_path = None
        if self.args.incremental:
            self.setCompareDst()
        if self.last_full_path is None:
            self.args.incremental = None  # Cannot find the previous back, disable incremental backup

        self.mkDst()
        self.archive_path = self.dst

        if self.args.cleanall:
            if self.args.clean_local_after is None:
                self.args.clean_local_after = 1
            if self.args.incremental:
                self.logger.warning("--cleanall cannot be used with --incremental. Disabled")
                self.args.cleanall = False

    def getLogger(self, level=logging.INFO):
        logger = logging.getLogger('BackupUtils')
        logger.setLevel(level)
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(logging.Formatter(
            fmt='%(asctime)s - [%(name)s] (%(levelname)s) - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'))
        logger.addHandler(ch)
        return logger

    def mkdir(self, path):
        """Create folder, dry run if self.args.noexec is true"""
        if self.args.verbose:
            print(f'mkdir {path}')

        if self.args.noexec:
            return
        os.makedirs(path)

    def rmdir(self, path):
        """Remote entire directory"""
        if self.args.verbose:
            print(f'rm -rf {path}')

        if self.args.noexec:
            return
        if os.path.isdir(path):
            return shutil.rmtree(path)
        else:
            return os.remove(path)

    def shell(self, cmd, ignore_error=False, return_obj=False, force_exe=False, **kwargs):
        if self.args.verbose:
            print(f'{" ".join(cmd)}')
        if self.args.noexec and not force_exe:
            return True

        result = subprocess.run(cmd, **kwargs)
        if not ignore_error:
            self.error_flags = self.error_flags or (result.returncode != 0)
            if (result.returncode != 0):
                self.logger.error(f'Command Error: {" ".join(cmd)}')

        if return_obj:
            return result
        else:
            return result.returncode == 0

    def getDateFromName(self, name):
        """Get date from file/folder name"""
        m = re.match("(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(.*)$", name)
        if m is None:
            return None, None
        return (datetime(year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)),
                         hour=int(m.group(4)), minute=int(m.group(5)), second=int(m.group(6))),
                m.group(7))

    def mkDst(self):
        """Create temporary folder if self.dst is None,
        then create a date_time folder under the dst
        """
        if self.dst is None:
            self.tempdir = tempfile.mkdtemp()
            self.logger.info(f'Created temporary folder {self.tempdir}')
            self.dst = self.tempdir

        assert os.path.isdir(self.dst), "Local output folder doesn't exist or cannot create:"
        f'{self.dst}'

        for i in range(100):  # iterate unitl folder name confliction is resolved
            dst_datetime = os.path.join(self.dst,
                                        datetime.now().strftime('%Y%m%d_%H%M%S'))
            if i > 0:
                dst_datetime += str(i)
            if not os.path.isdir(dst_datetime):
                self.dst = dst_datetime
                break

        if self.args.incremental:
            self.dst += "_diff"

        assert not os.path.isdir(self.dst)

        self.logger.info(f'Local output folder: {self.dst}')
        self.mkdir(self.dst)

    def findOldFolders(self, path):
        full_list = []
        diff_list = []
        if path is None or not os.path.isdir(path):
            return full_list, diff_list

        for folder in os.listdir(path):
            full_path = os.path.join(path, folder)
            file_date, suffix = self.getDateFromName(folder)
            if file_date is None:
                continue
            if len(suffix) == 0:
                full_list.append((full_path, file_date))
                continue

            if suffix == "_diff":
                diff_list.append((full_path, file_date))
                continue
        return full_list, diff_list

    def findOldZipArchives(self, path):
        zip_full_list = []
        zip_diff_list = []
        if path is None or not os.path.isdir(path):
            return zip_full_list, zip_diff_list

        for folder in os.listdir(path):
            full_path = os.path.join(path, folder)
            file_date, suffix = self.getDateFromName(folder)
            if file_date is None:
                continue

            if suffix[-3:] == ".7z" or suffix[-4:] == ".zip":
                if re.search("_diff", suffix):
                    zip_diff_list.append((full_path, file_date))
                else:
                    zip_full_list.append((full_path, file_date))
                continue

        return zip_full_list, zip_diff_list

    def setCompareDst(self):
        """Search the latest full and diff folders after the full
        to be used as a base folder"""

        # Initialize
        self.compare_full = None
        self.compare_diff = []

        if self.dst_root is None or not os.path.isdir(self.dst_root):
            return

        full_list, diff_list = self.findOldFolders(self.dst_root)

        if len(full_list) == 0:
            return

        p, d = sorted(full_list, key=lambda x: x[1])[-1]
        self.last_full_path = {'path': p, 'date': d}
        self.diff_after_full = {k: v for k, v in
                                filter(lambda x: x[1] > self.last_full_path['date'], diff_list)}

    def doWork(self):
        self.backupFolders()
        if self.args.mysql:
            self.saveMysql()
        if not self.args.nocompress:
            self.zipBackup()

        if self.args.remote:
            self.uploadToRemote()

        if not self.error_flags and self.args.clean_local_after is not None:
            self.cleanLocalFolder()

        if not self.error_flags and self.args.clean_remote_after is not None:
            self.cleanRemoteFolder()

    def backupFolders(self):
        """Backup each source folder"""
        for src_path in self.src_list:
            if not os.path.exists(src_path):
                self.logger.warning(f"Source path '{src_path}' doesn't exist")
                continue

            self.backupFolder(self.dst, src_path)

    def backupFolder(self, dst_path, src_path):
        if os.path.isfile(src_path):
            dst_path = os.path.join(dst_path, os.path.basename(src_path))

        cmd = ['rsync', '-ah', ]

        if self.args.incremental:
            cmd.extend(['--compare-dest', os.path.abspath(self.last_full_path['path'])])
            for pre_diff in self.diff_after_full.keys():
                cmd.extend(['--compare-dest', os.path.abspath(pre_diff)])

        cmd.extend([src_path, dst_path])
        self.logger.info(f"Copying {src_path} to {dst_path}")

        result = self.shell(cmd)

    def saveMysql(self):
        """Save mySQL database"""
        dst_file = os.path.join(self.dst, 'mysqldump_all_database.sql')
        cmd = ['mysqldump', '--all-databases', '-C', '--result-file', dst_file]

        self.logger.info(f"Dumping all mySql database to {dst_file}")

        result = self.shell(cmd)

    def zipBackup(self):
        """Zipping output folder"""

        cwd = os.getcwd()
        os.chdir(os.path.dirname(self.dst))

        if self.args.zip:
            cmd = ['zip', '-r', '-9', '-y']
            if self.args.password:
                cmd.extend(['-e', '-P', self.args.password])
            self.archive_path = os.path.abspath(os.path.basename(self.dst) + '.zip')
            cmd.append(self.archive_path)
            cmd.append(os.path.basename(self.dst))
        else:
            cmd = ['7z', 'a', '-r']
            if self.args.password:
                cmd.append(f'-p{self.args.password}')
                cmd.append('-mhe=on')
            self.archive_path = os.path.abspath(os.path.basename(self.dst) + '.7z')
            cmd.append(self.archive_path)
            cmd.append(os.path.basename(self.dst))

        result = self.shell(cmd)

        os.chdir(cwd)

    def createRemoteFolder(self, dst):
        """Check existence of the remote folder,
        and create a folder if it doesn't"""
        cmd = ['rclone', 'lsd', dst]
        if not self.shell(cmd, ignore_error=True):
            cmd = ['rclone', 'mkdir', dst]
            return self.shell(cmd)

        return True

    def rmRemote(self, path):
        cmd = ['rclone', 'delete', path]
        return self.shell(cmd)

    def getRemoteFiles(self, path):
        cmd = ['rclone', 'ls', path]
        result = self.shell(cmd, stdout=subprocess.PIPE, encoding='utf8', return_obj=True, force_exe=True)
        if result.returncode != 0:
            self.logger.error(f'Failed to ls remote path "{path}"')
            return

        file_list = []
        for line in result.stdout.split('\n'):
            if len(line) == 0:
                continue
            file_list.append(line.split()[1])
        return file_list

    def uploadToRemote(self):
        """Upload backup archive to remote storage"""

        if not self.createRemoteFolder(self.args.remote):
            self.logger.error("Failed to create remote target folder")
            return

        src_path = self.archive_path
        self.logger.info(f'Uploading archive {src_path} to {self.args.remote}')
        cmd = ['rclone', 'copy', src_path, self.args.remote]
        if not self.shell(cmd):
            self.logger.error(f"Failed to upload to remote (cmd: {' '.join(cmd)})")

    def cleanLocalFolder(self):
        """Delete old archives
           - Delete tempdir
           - In incremental mode, delete old *_diff after a full backup before specified days
           - In fullbackup mode, delete old full backup folders and *_diff before specified days
           - Delete compressed file when --remote presents
        """
        full_list, diff_list = self.findOldFolders(self.dst_root)
        zip_full_list, zip_diff_list = self.findOldZipArchives(self.dst_root)

        if self.tempdir is not None:
            self.rmdir(self.tempdir)
            return

        target_date = datetime.now() - timedelta(days=self.args.clean_local_after)
        tobe_deleted_list = []
        full_before_target = []
        for path, date in sorted(full_list + zip_full_list, key=lambda x: x[1])[0:-1]:
            if date < target_date:
                full_before_target.append((path, date))

        if len(full_before_target) > 0:
            latest_rm_full = full_before_target[-1][1]
            self.logger.debug(f'Target Full Backup Date: {latest_rm_full}')
            # find old diff before target full back
            for path, date in sorted(diff_list + zip_diff_list, key=lambda x: x[1]):
                if date < latest_rm_full:
                    tobe_deleted_list.append((path, date))

            if not self.args.incremental:
                tobe_deleted_list.extend(full_before_target)

        for path, date in tobe_deleted_list:
            self.rmdir(path)

        if not self.args.nocompress and self.args.remote:
            self.rmdir(self.archive_path)

        if self.args.cleanall:
            if not self.args.nocompress:
                self.rmdir(self.dst)

    def cleanRemoteFolder(self):
        """Delete old archives on remote storage
           - when incremental mode
             + Delete all *_diff archive older than specified days
           - when full backup mode
             + Delete old full backup archive older than specified days
        """
        remote_file_list = self.getRemoteFiles(self.args.remote)

        full_archive_list = []
        diff_archive_list = []

        for name in remote_file_list:
            file_date, suffix = self.getDateFromName(name)
            if file_date is None:
                continue

            if re.search("_diff.(7z|zip)", name):
                diff_archive_list.append((name, file_date))
            elif suffix == '.7z' or suffix == '.zip':
                full_archive_list.append((name, file_date))

        today = datetime.now()
        rm_days = today - timedelta(days=self.args.clean_remote_after)
        if self.args.incremental:
            # Delete diff archive older than specifid days
            for path, date in diff_archive_list:
                if date < rm_days:
                    self.rmRemote(self.args.remote + '/' + path)

        else:
            # Delete full archive older than specifid days
            for path, date in full_archive_list:
                if date < rm_days:
                    self.rmRemote(self.args.remote + '/' + path)


def main():

    parser = argparse.ArgumentParser()

    BackupUtils.add_options(parser)

    args = parser.parse_args()

    backup_util = BackupUtils(args)
    backup_util.doWork()


if __name__ == "__main__":
    main()

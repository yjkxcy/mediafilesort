# mediafilesort
### 照片和视频文件的整理
根据拍摄日期或者文件最后修改日期生成子目录并复制文件到该目录

usage: mediafilesort.py [-h] [-t  [...]] [-s] [-c] [-d] [-a] srcp destp<br>

positional arguments:<br>
  srcp                  源文件目录<br>
  destp                 目标目录<br>

options:<br>
  -h, --help            show this help message and exit<br>
  -t  [ ...], --ftype  [ ...]
                        自定义文件类型<br>
  -s, --scanflag        不扫描源目录下文件，只输出源目录的统计信息<br>
  -c, --copyflag        不复制文件到目标目录，只统计需复制的文件数量<br>
  -d, --delflag         已存在或复制成功后删除源文件<br>
  -a, --addtypeflag     在系统默认的文件类型上增加新的文件类型<br>

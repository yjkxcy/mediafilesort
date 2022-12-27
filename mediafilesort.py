import time
import hashlib
import shutil
import re
import sys
import logging
import logging.handlers
import pickle
import argparse
import exifread
from pathlib import Path, PurePath

LOGFILE = 'mediafilesort.log'  #日志文件
DEL_FLAG = False          #删除源文件标志
SCAN_FLAG = False         #是否扫描目录标志
COPY_FLAG = False         #是否执行复制动作
ADDTYPE_FLAG = False      #True在默认基础上再增加文件类型，False自定义文件类型

def initLogger(name=__name__):
	'''返回自定义日志，同时在终端和文件中输出日志信息，默认日志级别，终端DEBUG、文件INFO'''
	logger = logging.getLogger(name)
	logger.setLevel(logging.DEBUG)
	formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	#设置终端
	ch = logging.StreamHandler()
	ch.setLevel(logging.DEBUG)
	ch.setFormatter(formatter)
	logger.addHandler(ch)
	#设置日志文件
	rotating_handler = logging.handlers.RotatingFileHandler(LOGFILE, encoding='utf-8', maxBytes=102400, backupCount=10)
	rotating_handler.setLevel(logging.INFO)
	rotating_handler.setFormatter(formatter)
	logger.addHandler(rotating_handler)
	#返回日志实例
	return logger

logger = initLogger()

def fileMd5(fname):
	'''返回文件的MD5码'''
	size = 8192
	fmd5 = hashlib.md5()
	with open(fname, 'rb') as f:
		while True:
			data = f.read(size)
			if not data:
				break
			fmd5.update(data)
	logger.debug(f"文件 '{Path(fname).name}' 的MD5码: {fmd5.hexdigest()}")
	return fmd5.hexdigest()

def matchfmt(datetime):
	'''匹配不同的EXIF日期的格式，返回日期和日期格式'''
	fmt = ['%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S']       #转换函数time.strptime()的日期格式
	#正则匹配时间格式 2022:04:15 20:22:56，2022-04-15 20:22:56
	pattern = [ r'(\d{4}):(1[0-2]|0[1-9]):([1-2]\d|3[0-1]|0[1-9]) ([0-1]\d|2[0-4]):([0-5]\d):([0-5]\d)',
				r'(\d{4})-(1[0-2]|0[1-9])-([1-2]\d|3[0-1]|0[1-9]) ([0-1]\d|2[0-4]):([0-5]\d):([0-5]\d)']
	for p, f in zip(pattern, fmt):
		result = re.match(p, datetime)
		if result:
			return (result.group(0), f)
	raise ValueError(f"时间格式没有匹配成功")

def readEXIFdateTimeOriginal(fname):
	'''返回照片的拍摄日期（时间戳），读取错误返回None'''
	date = None
	with open(fname, 'rb') as f:
		try:
			pattern = re.compile(r'(\d{4}):(1[0-2]|0[1-9]):([1-2]\d|3[0-1]|0[1-9]) ([0-1]\d|2[0-4]):([0-5]\d):([0-5]\d)')
			tags = exifread.process_file(f, details=False, stop_tag='DateTimeOriginal')
			if 'EXIF DateTimeOriginal' in tags.keys():
				logger.debug(f"文件拍摄日期的原始格式: {tags['EXIF DateTimeOriginal'].values}")
				if not re.match(pattern, tags['EXIF DateTimeOriginal'].values):
					logger.warning(f"特殊的文件拍摄日期原始格式: {tags['EXIF DateTimeOriginal'].values}")  #不同时间格式
				datetimeoriginal, dateformat = matchfmt(tags['EXIF DateTimeOriginal'].values)
				date = time.mktime(time.strptime(datetimeoriginal, dateformat)) #转换为时间戳
		except Exception as e:
			logger.error(f"读文件的EXIF信息失败: {fname} 错误: {e}")
	return date
#re.compile(r'^(0?[0-9]|1[0-9]|2[0-3]):(0?[0-9]|[1-5][0-9]):(0?[0-9]|[1-5][0-9])$')  匹配时间
#r'[\-\:\s\_\/]?([0-1]\d|2[0-4])[\-\:\s\_\/]?([0-5]\d)[\-\:\s\_\/]?([0-5]\d)'  匹配时间
#r'(\d{4})[\-\:\s\_\/]?(1[0-2]|0[1-9])[\-\:\s\_\/]?([1-2]\d|3[0-1]|0[1-9])'  匹配日期

class FileType(object):
	'''文件类型相关的处理函数集合'''
	_pic = {'.jpg', '.png', '.jpeg'}    #默认处理的照片文件
	_video = {'.mp4', '.avi', '.mov'}    #默认处理的视频文件

	@classmethod
	def pictype(cls):
		'''照片类文件'''
		return cls._pic

	@classmethod
	def videotype(cls):
		'''视频类文件'''
		return cls._video

	@classmethod
	def typemap(cls, suffix):
		'''根据扩展名返回合适的文件类型标识：照片(PIC)、视频(VIDEO)、普通(COMMON)'''
		if suffix.lower() in ['.jpg', '.jpeg', '.png']:    #可能带EXIF的文件
			return 'PIC'
		elif suffix.lower() in cls._video:
			return 'VIDEO'
		else:
			return 'COMMON'

	@classmethod
	def add(cls, suffix):
		'''添加额外的文件类型，suffix：文件扩展名（如 '.mpeg'）'''
		pic = ['.bmp', '.tif', '.gif']                   #限制乱添加
		video = ['.mpg', '.mpeg', '.3gp', '.dat', '.mkv', '.rm', 'rmvb']   #限制乱添加
		suffix = suffix.lower()
		if suffix in pic:
			cls._pic.add(suffix)     #添加到照片文件集合
		elif suffix in video:
			cls._video.add(suffix)   #添加到视频文件集合
		else:
			raise ValueError(f"不是支持的文件类型，添加失败: {suffix}")

class FolderFormat(object):
	'''子目录名的样式，现支持3种：20221227 202212 2022'''
	fmtdict = {'day': '%Y%m%d', 'month': '%Y%m', 'year': '%Y'}
	datefmt = '%Y%m%d'

	@classmethod
	def setfmt(cls, fmt):
		if fmt:
			if fmt.lower() in ('day', 'month', 'year'):
				cls.datefmt = cls.fmtdict[fmt.lower()]
			else:
				cls.datefmt = '%Y%m%d'
		else:
			cls.datefmt = '%Y%m%d'

class FileStats(object):
	'''文件状态信息，basename文件名、savedir保存的子目录名、fmd5文件的fmd5码'''
	def __init__(self, fname):
		self._fname = Path(fname)
		self._basename = self._fname.name
		self._fmd5 = fileMd5(fname)   #生成MD5码，未考虑发生异常
		self._savedir = self._subdir()  #生成子目录，格式: 20221128

	@property
	def basename(self):
		'''返回文件名，如 name.jpg'''
		return self._basename

	@property
	def savedir(self):
		'''返回文件需保存到的子目录名'''
		return self._savedir

	@property
	def fmd5(self):
		'''返回文件的MD5码'''
		return self._fmd5

	# def _fileMd5(self):
	# 	'''返回文件的MD5码，异常处理'''
	# 	try:
	# 		fmd5 = fileMd5(self._fname)
	# 	except Exception as e:
	# 		pass
	# 	return fmd5

	def ftime(self):
		'''返回文件的各种日期(最后修改日期、照片的拍摄日期、视频的拍摄日期)，子类通过覆写该函数实现返回不同日期'''
		return self._fname.stat().st_mtime   #最后修改日期

	def _subdir(self):
		'''返回需保存到的子目录名，如: '20221128', '202211', '2022' '''
		folderformat = FolderFormat.datefmt    #子目录名格式
		return time.strftime(folderformat, time.localtime(self.ftime()))

class JpgFileStats(FileStats):
	'''JPG文件或其他带EXIF信息的文件'''
	def __init__(self, fname):
		self._dateTimeOriginal = readEXIFdateTimeOriginal(fname)  #获取拍摄日期
		super().__init__(fname)

	@property
	def dateTimeOriginal(self):
		if self._dateTimeOriginal == None:
			raise ValueError(f"文件没有EXIF信息: {self._fname}")   #考虑抛出异常
		return self._dateTimeOriginal

	def ftime(self):
		'''覆写父类，如果文件有拍摄日期，返回拍摄日期，否则返回最后修改日期'''
		fdate = self._fname.stat().st_mtime   
		logger.debug(f"文件的最后修改日期: {fdate}")
		if self._dateTimeOriginal:
			fdate = self._dateTimeOriginal    #如果有拍摄日期
			logger.debug(f"文件的拍摄日期: {fdate}")
		return fdate   #返回值: 时间戳

class VideoFileStats(FileStats):
	'''视频文件'''
	pass

#对文件类的映射
FILE_TYPE_MAP = {'PIC': JpgFileStats, 'VIDEO': VideoFileStats, 'COMMON': FileStats}

def fileTransfer(fname):
	'''根据不同的文件类型，使用不同的类实例化，JpgFileStats VideoFileStats FileStats'''
	suffix = PurePath(fname).suffix
	ftype = FileType.typemap(suffix)
	FileTransferClass = FILE_TYPE_MAP[ftype]  #赋值不同的类名
	return FileTransferClass(fname)

class MediaFolder(object):
	'''保存多媒体文件（照片、视频）的目录'''
	def __init__(self, fpath):
		self._fpath = Path(fpath)
		self._fmd5s = self._scan()

	@property
	def fmd5s(self):
		'''返回目录下所有文件的MD5码的列表'''
		return self._fmd5s

	def _sumfiles(self):
		'''统计该目录下所有子目录中的文件数量'''
		allfiles = len([f for f in self._fpath.rglob('*.*') if f.is_file()])
		return allfiles - len([f for f in self._fpath.glob('*.*') if f.is_file()])

	def _readfmd5file(self):
		'''搜索目录下存放fmd5码的文件，读取后返回list，没有正确读取到返回空列表'''
		fmd5s = []
		fname = Path(self._fpath, 'fmd5.dat')
		if Path(fname).exists():
			try:
				with open(fname, 'rb') as f:
					fmd5s = pickle.load(f)
			except Exception as err:
				logger.error(f"fmd5码文件读取错误: {err}")
		return fmd5s if len(fmd5s)==self._sumfiles() else []  #数量核对有差异返回空list

	def _scan(self):
		'''获取目录下所有文件的MD5码，先检查是否存在fmd5.dat文件，有就读取，否就扫描目录生成fmd5码'''
		fmd5s = self._readfmd5file()      #读存放fmd5码的文件
		if not fmd5s:
			excludefile = list(self._fpath.glob('*.*')) #排除备份目录下一级目录中的文件
			for f in self._fpath.rglob('*.*'):
				if Path(f).is_file() and f not in excludefile:
					fmd5s.append(fileMd5(f))  #生成fmd5码并添加到列表
			if len(fmd5s) != self._sumfiles():
				raise ValueError(f"fmd5码数量和实际文件数不同")
		return fmd5s

	def writefmd5file(self):
		'''复制文件完成，保存fmd5码到文件中'''
		fname = Path(self._fpath, 'fmd5.dat')
		filecount = self._sumfiles()
		fmd5len = len(self._fmd5s)
		if filecount == fmd5len:
			try:
				with open(fname, 'wb') as f:
					pickle.dump(self._fmd5s, f)
				logger.info(f"fmd5码文件保存成功")
			except Exception as err:
				logger.error(f"fmd5码文件写入错误: {err}")
		else:
			logger.error(f"fmd5码保存时数量核对不正确，保存失败: fmd5={fmd5len} filecount={filecount}")


	def exists(self, fname):
		'''判断文件是否存在'''
		try:
			fmd5 = fileMd5(fname)
		except Exception as e:
			raise ValueError(f"文件的MD5码获取失败: {fname} 错误原因: {e}")
		return fmd5 in self._fmd5s

	def _rename(self, destf):
		'''重新命名，直到文件名不存在'''
		count = 1
		fpath = Path(destf).parent
		fstem = Path(destf).stem
		suffix = Path(destf).suffix
		fname = ''.join((fstem, f"_{count}", suffix))
		while Path(fpath, fname).exists():
			count += 1
			fname = ''.join((fstem, f"_{count}", suffix))
		return Path(fpath, fname)

	def _safecopy(self, srcf, destp):
		'''拷贝文件到目标目录，如果存在相同文件名，在文件名后加上数字后缀'''
		destf = Path(destp, Path(srcf).name)
		logger.debug(f"目标文件名: {destf}")
		if destf.exists():
			destf = self._rename(destf) #文件名存在，重新命名
			logger.warning(f"重命名后目标文件名: {destf}")
		try:
			shutil.copy2(srcf, destf)
			return True
		except Exception as e:
			logger.error(f"复制文件错误: {srcf}, 错误原因: {e}")
			return False


	def copy(self, srcfile):
		'''按照文件的各种时间属性生成子目录，复制文件到子目录中'''
		try:
			fstats = fileTransfer(srcfile)
		except Exception as e:
			logger.error(f"获取文件基本信息失败: {srcfile}")
			return False                      #复制失败
		if fstats.fmd5 in self._fmd5s:
			logger.debug(f"文件已经存在: {srcfile}")
			if DEL_FLAG:
				Path(srcfile).unlink()    #已存在，删除文件
			return False                     #复制失败
		else:
			subdir = Path(self._fpath, fstats.savedir)
			if not subdir.exists():
				Path.mkdir(subdir)
				logger.info(f"新建文件夹: {subdir}")
			if self._safecopy(srcfile, subdir):
				self._fmd5s.append(fstats.fmd5)
				logger.debug(f"复制文件 {srcfile} 到 {subdir} 中成功")
				if DEL_FLAG:
					Path(srcfile).unlink()   #复制成功，删除文件
				return True                 #返回复制成功
			else:
				return False                #返回复制失败

def countFtype(folder):
	'''统计目录下所有文件的类型，返回目录下存在的需要的文件类型，如无返回空集合'''
	ftypes = FileType.pictype() | FileType.videotype()  #默认需要的文件类型 并集
	suffix_list = set([f.suffix.lower() for f in Path(folder).rglob('*.*') if f.is_file()])  #目录下所有文件类型
	otherftype = suffix_list - ftypes    #差集
	if otherftype:
		logger.info(f"目录下其他文件类型有: {otherftype}")
	needftype = suffix_list & ftypes     #交集
	if needftype:
		logger.info(f"目录下存在的需要的文件类型: {needftype}")
	return needftype   #如无返回空集合

def scanFolder(srcp, needftype):
	'''返回目录下指定类型的文件'''
	if needftype:         #避免值为None时产生异常
		for ftype in needftype:
			for f in Path(srcp).rglob(f"*{ftype}"):  # "*.jpg"
				if f.is_file():
					yield f

def main(srcp, destp, ftype=None):
	try:
		mfolder = MediaFolder(destp)    #目标目录实例化
	except Exception as err:
		logger.error(f"fmd5码核对错误: {err}")
		return
	needftype = countFtype(srcp)   #系统预设文件类型
	if ftype:
		if ADDTYPE_FLAG:
			needftype = needftype | ftype    #合并文件类型
		else:
			needftype = ftype            #用户自定义文件类型
	if not needftype:
		logger.warning(f"需要扫描的文件类型为空")
		return
	if SCAN_FLAG:              #扫描文件开关，不扫描只输出文件类型的统计信息
		logger.info(f"此次扫描的文件类型: {needftype}")
		if COPY_FLAG:          #复制文件开关
			copy = mfolder.copy
		else:
			copy = lambda x: False
		copyresult = list(map(copy, scanFolder(srcp, needftype)))
		logger.info(f"文件总数: {len(copyresult)}, 复制成功数: {copyresult.count(True)}")
		if copyresult.count(True):
			mfolder.writefmd5file()     #保存fmd5码到文件中

		


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='按时间整理照片或视频文件')
	parser.add_argument('srcp', help='源文件目录')
	parser.add_argument('destp', help='目标目录')
	parser.add_argument('-t', '--ftype', nargs='+', metavar='', help='自定义文件类型')
	parser.add_argument('-f', '--format', choices=['day', 'month', 'year'], help='子目录的样式')
	parser.add_argument('-s', '--scanflag', action='store_false', help='不扫描源目录下文件，只输出源目录的统计信息')
	parser.add_argument('-c', '--copyflag', action='store_false', help='不复制文件到目标目录，只统计需复制的文件数量')
	parser.add_argument('-d', '--delflag', action='store_true', help='已存在或复制成功后删除源文件')
	parser.add_argument('-a', '--addtypeflag', action='store_true', help='在系统默认的文件类型上增加新的文件类型')
	args = parser.parse_args()
	# print(args.srcp, args.destp, args.ftype, args.scanflag, args.copyflag, args.delflag, args.addtypeflag)
	if not Path(args.srcp).exists():
		logger.error(f"源目录不存在: {args.srcp}")
		sys.exit(1)
	if not Path(args.destp).exists():
		logger.error(f"目标目录不存在: {args.destp}")
		sys.exit(1)
	#标准化文件类型格式
	if args.ftype:
		ftype = set()
		for ft in args.ftype:
			result = re.search(r'\w{2,4}', ft)
			# print(result.group(0))
			if result:
				ftype.add(f".{result.group(0)}")   #标准化文件扩展名,形如: '.jpg'
	else:
		ftype = None
	# print(ftype)
	#赋值全局变量
	SCAN_FLAG = args.scanflag
	COPY_FLAG = args.copyflag
	DEL_FLAG = args.delflag
	ADDTYPE_FLAG = args.addtypeflag
	FolderFormat.setfmt(args.format)   #设置子目录名样式
	# print(FolderFormat.datefmt)
	#调用主函数，传入命令行输入的参数
	main(args.srcp, args.destp, ftype=ftype)



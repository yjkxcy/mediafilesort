import time
import hashlib
import shutil
import logging
import logging.handlers
import pickle
import exifread
from pathlib import Path, PurePath

LOGFILE = 'mediafilesort.log'  #日志文件
DEL_FLAG = False          #删除源文件标志
SCAN_FLAG = False         #是否扫描目录标志
COPY_FLAG = False         #是否执行复制动作

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

def readEXIFdateTimeOriginal(fname):
	'''返回照片的拍摄日期（时间戳），读取错误返回None'''
	dateformat = '%Y:%m:%d %H:%M:%S'
	date = None
	with open(fname, 'rb') as f:
		try:
			tags = exifread.process_file(f, details=False)
			if 'EXIF DateTimeOriginal' in tags.keys():
				logger.debug(f"文件拍摄日期的原始格式: {tags['EXIF DateTimeOriginal']}")
				date = time.mktime(time.strptime(str(tags['EXIF DateTimeOriginal']), dateformat))
		except Exception as e:
			logger.error(f"读文件的EXIF信息失败: {fname}")
			return None
	return date


class NeedFileType(object):
	'''需要处理的文件的类型'''
	@staticmethod
	def PICTYPE():
		'''照片类文件'''
		return {'.jpg'}   #集合类型

	@staticmethod
	def VIDEOTYPE():
		'''视频类文件'''
		return {'.mp4'}  #集合类型


def chooseFileType(suffix):
	'''根据扩展名返回合适的文件类型标识：照片(PIC)、视频(VIDEO)、普通(COMMON)'''
	if suffix.lower() in NeedFileType.PICTYPE():
		return 'PIC'
	elif suffix.lower() in NeedFileType.VIDEOTYPE():
		return 'VIDEO'
	else:
		return 'COMMON'

class FileStats(object):
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
		return self._fname.stat().st_mtime

	def _subdir(self):
		'''返回需保存到的子目录名，如: '20221128' '''
		folderformat = '%Y%m%d'    #子目录名格式
		return time.strftime(folderformat, time.localtime(self.ftime()))

class JpgFileStats(FileStats):
	'''JPG文件'''
	def __init__(self, fname):
		self._dateTimeOriginal = readEXIFdateTimeOriginal(fname)
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
			fdate = self._dateTimeOriginal
			logger.debug(f"文件的拍摄日期: {fdate}")
		return fdate   #返回值: 时间戳

class VideoFileStats(FileStats):
	'''视频文件'''
	pass



#对文件类的映射
FILE_TYPE_MAP = {'PIC': JpgFileStats, 'VIDEO': VideoFileStats, 'COMMON': FileStats}

#根据不同文件类型选用合适的文件类
def fileTransfer(fname):
	'''根据不同的文件类型，使用不同的类'''
	suffix = PurePath(fname).suffix
	ftype = chooseFileType(suffix)
	FileTransferClass = FILE_TYPE_MAP[ftype]
	return FileTransferClass(fname)

class MediaFolder(object):
	'''保存多媒体文件（照片、视频）的目录'''
	def __init__(self, fpath):
		self._fpath = Path(fpath)
		self._fmd5s = self._scan()

	@property
	def fmd5s(self):
		'''返回目录下所以文件的MD5码的列表'''
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

	def writefmd5file(self):
		'''复制文件完成，保存fmd5码到文件中'''
		fname = Path(self._fpath, 'fmd5.dat')
		if len(self._fmd5s) == self._sumfiles():
			try:
				with open(fname, 'wb') as f:
					pickle.dump(self._fmd5s, f)
			except Exception as err:
				logger.error(f"fmd5码文件写入错误: {err}")
				return
			logger.info(f"fmd5码文件保存成功")
		else:
			logger.error(f"fmd5码保存时数量核对不正确，保存失败")


	def _scan(self):
		'''获取目录下所有文件的MD5码'''
		fmd5s = self._readfmd5file()
		if not fmd5s:
			for f in self._fpath.rglob('*.*'):
				if Path(f).is_file() and f not in list(self._fpath.glob('*.*')):
					try:
						fmd5s.append(fileMd5(f))
					except Exception as e:
						logger.error(f"获取文件MD5码错误: {f}")
						continue
		return fmd5s

	def exists(self, fname):
		'''判断文件是否存在'''
		try:
			fmd5 = fileMd5(fname)
		except Exception as e:
			raise ValueError(f"文件的MD5码获取失败: {fname}")
		return fmd5 in self._fmd5s

	def _rename(self, destf):
		'''重新命名，直到文件不存在'''
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
		destf = Path(destp, Path(srcf).name)
		logger.debug(f"目标文件名: {destf}")
		if destf.exists():
			destf = self._rename(destf) #文件存在，重新命名
			logger.debug(f"重命名后目标文件名: {destf}")
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
				logger.info(f"复制文件 {srcfile} 到 {subdir} 中成功")
				if DEL_FLAG:
					Path(srcfile).unlink()   #复制成功，删除文件
				return True                 #复制成功
			else:
				return False                #复制失败


def countFtype(folder):
	'''统计目录下所有文件的类型，返回存在的需要的文件类型'''
	ftypes = NeedFileType.PICTYPE() | NeedFileType.VIDEOTYPE()  #需要的文件类型 并集
	suffix_list = set([f.suffix.lower() for f in Path(folder).rglob('*.*') if f.is_file()])
	otherftype = suffix_list - ftypes    #差集
	if otherftype:
		logger.info(f"目录下其他文件类型有: {otherftype}")
	needftype = suffix_list & ftypes     #交集
	if needftype:
		logger.info(f"目录下存在的需要的文件类型: {needftype}")
	return needftype

def scanFolder(srcp, needftype):
	'''返回目录下指定类型的文件'''
	# needftype = countFtype(srcp)
	if needftype:
		for ftype in needftype:
			for f in Path(srcp).rglob(f"*{ftype}"):
				if f.is_file():
					yield f


def main(srcp, destp):
	SCAN_FLAG = True
	COPY_FLAG = True
	mfolder = MediaFolder(destp)
	needftype = countFtype(srcp)
	# print(needftype)
	if SCAN_FLAG:              #扫描文件开关
		if COPY_FLAG:          #复制文件开关
			copy = mfolder.copy
		else:
			copy = lambda x: False
		copyresult = list(map(copy, scanFolder(srcp, needftype)))
		logger.info(f"文件总数: {len(copyresult)}, 复制成功数: {copyresult.count(True)}")
	mfolder.writefmd5file()     #保存fmd5码到文件中

		




if __name__ == '__main__':
	# srcfile = 'd:\\浙江人事考试网.txt'
	# srcfile = 'd:\\pictest.jpg'
	# srcfile = 'd:\\000_1832.jpg'
	# mfolder = MediaFolder(r'd:\copytest')
	# print(mfolder.fmd5s)
	# mfolder.writefmd5file()
	# mfolder.copy(srcfile)
	# fstats = fileTransfer(srcfile)
	# print(f"文件名: {fstats.basename}  子目录: {fstats.savedir}  MD5码: {fstats.fmd5}")
	# print(list(scanFolder(r'c:\\')))
	# copyresult = list(map(mfolder.copy, scanFolder(r'd:\copytest')))
	# print(copyresult.count(False))
	# print(NeedFileType.PICTYPE() | NeedFileType.VIDEOTYPE())
	main(r'd:\copytest', r'd:\copytest1')


# -*- coding: utf-8 -*-

import sys, os
from PIL import Image
p = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if p not in sys.path:
    sys.path.insert(0, p)

import os, platform, uuid, subprocess, time

from qqbot.utf8logger import WARN, INFO, DEBUG
from qqbot.common import StartDaemonThread, LockedValue, HasCommand, PY3, PrintCmdQrcode
from qqbot.qrcodeserver import QrcodeServer
from qqbot.mailagent import MailAgent

class QrcodeManager(object):
    def __init__(self, conf):
        qrcodeId = uuid.uuid4().hex
        self.qrcodePath = conf.QrcodePath(qrcodeId)
        if conf.httpServerIP:
            self.qrcodeServer = QrcodeServer(
                conf.httpServerIP,
                conf.httpServerPort,
                os.path.dirname(self.qrcodePath)
            )
            self.qrcodeURL = self.qrcodeServer.qrcodeURL
        else:
            self.qrcodeServer = None        

        if conf.mailAccount:
            self.mailAgent = MailAgent(
                conf.mailAccount, conf.mailAuthCode, name='QQBot管理员'
            )
            
            if self.qrcodeServer:
                html = ('<p>您的 QQBot 正在登录，请尽快用手机 QQ 扫描下面的二维码。'
                        '若二维码已过期，请重新打开本邮件。若您看不到二维码图片，请确保'
                        '图片地址 <a href="{0}">{0}</a> 可以通过公网访问。</p>'
                        '<p><img src="{0}"></p>').format(self.qrcodeURL)
            else:
                html = ('<p>您的 QQBot 正在登录，请尽快用手机 QQ 扫描下面的二维码。'
                        '若二维码已过期，请将本邮件设为已读邮件，之后 QQBot 会在'
                        '1~2分钟内将最新的二维码发送到本邮箱。</p>'
                        '<p>{{png}}</p>')

            self.qrcodeMail = {
                'to_addr': conf.mailAccount,
                'html': html,
                'subject': ('%s[%s]' % ('QQBot二维码', qrcodeId)),
                'to_name': '我'
            }
            
            self.qrcode = LockedValue(None)

        else:
            self.mailAgent = None
        
        self.cmdQrcode = conf.cmdQrcode
    
    def Show(self, qrcode):
        with open(self.qrcodePath, 'wb') as f:
            f.write(qrcode)
        
        if self.cmdQrcode:
            try:
                showCmdQRCode(self.qrcodePath)
            except Exception as e:
                WARN('无法以文本模式显示二维码图片 file://%s 。%s',
                     self.qrcodePath, e)
        
        if not (self.qrcodeServer or self.mailAgent or self.cmdQrcode):
            try:
                showImage(self.qrcodePath)
            except Exception as e:
                WARN('无法弹出二维码图片 file://%s 。%s', self.qrcodePath, e)

        if self.qrcodeServer:
            INFO('请使用浏览器访问二维码，图片地址： %s', self.qrcodeURL)
        
        if self.mailAgent:
            if self.qrcode.getVal() is None:
                self.qrcode.setVal(qrcode)
                # first show, start a thread to send emails
                StartDaemonThread(self.sendEmail)
            else:
                self.qrcode.setVal(qrcode)
    
    def sendEmail(self):
        lastSubject = ''
        while True:
            if lastSubject != self.qrcodeMail['subject']:
                qrcode = self.qrcode.getVal()            
                if qrcode is None:
                    break
                qrcode = '' if self.qrcodeServer else qrcode
                try:
                    with self.mailAgent.SMTP() as smtp:
                        smtp.send(png_content=qrcode, **self.qrcodeMail)
                except Exception as e:
                    WARN('无法将二维码发送至邮箱%s %s', self.mailAgent.account, e)
                else:
                    INFO('已将二维码发送至邮箱%s', self.mailAgent.account)
                    if self.qrcodeServer:
                        break
                    else:
                        lastSubject = self.qrcodeMail['subject']
            else:
                time.sleep(65)
                qrcode = self.qrcode.getVal()            
                if qrcode is None:
                    break
                try:
                    DEBUG('开始查询邮箱 %s 中的最近的邮件', self.mailAgent.account)
                    with self.mailAgent.IMAP() as imap:
                        lastSubject = imap.getSubject(-1)
                except Exception as e:
                    WARN('查询邮箱 %s 中的邮件失败 %s', self.mailAgent.account, e)
                else:
                    DEBUG('最近的邮件： %s', lastSubject)
    
    def Destroy(self):
        if self.mailAgent:
            self.qrcode.setVal(None)

        try:
            os.remove(self.qrcodePath)
        except OSError:
            pass

# py2: FILENAME must be an utf8 encoding string
def showImage(filename):
    osName = platform.system()
    if osName == 'Windows':
        if not PY3:
            filename = filename.decode('utf8').encode('cp936')
        subprocess.Popen([filename], shell=True)
    elif osName == 'Linux':
        if HasCommand('gvfs-open'):
            subprocess.Popen(['gvfs-open', filename])
        elif HasCommand('shotwell'):
            subprocess.Popen(['shotwell', filename])
        else:
            raise
    elif osName == 'Darwin': # by @Naville
        subprocess.Popen(['open', filename])
    else:
        raise

def showCmdQRCode(filename):
    # 165x165 -> 33x33
    size=33
    padding=1
    rgb=Image.open(filename).resize((size,size)).convert('RGB')
    
    qrtext = '0' * (size + padding * 2) + '\n'
    for rr in range(size):
        qrtext += '0'*padding
        for cc in range(size):
            r,g,b = rgb.getpixel((cc,rr))
            if (r > 127 or g > 127 or b > 127):
                qrtext += '0'
            else:
                qrtext += '1'
        qrtext += '0'*padding
        qrtext += '\n'
    qrtext = qrtext + '0' * (size + padding * 2) + '\n'
    PrintCmdQrcode(qrtext)

if __name__ == '__main__':
    from qconf import QConf

    # 需要先在 ~/.qqbot-tmp/v2.x.conf 文件中设置好邮箱帐号和授权码
    conf = QConf()
    conf.Display()

    qrm = QrcodeManager(conf)
    with open('tmp.png', 'rb') as f:
        qrcode = f.read()
    qrm.Show(qrcode)
    time.sleep(5)
    qrm.Show(qrcode)
    qrm.Destroy()
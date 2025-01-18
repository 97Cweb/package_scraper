import email, getpass, imaplib, os, re

user = raw_input("Enter your GMail username --> ")
pwd = getpass.getpass("Enter your password --> ")

m = imaplib.IMAP4_SSL("imap.gmail.com")
m.login(user, pwd)
m.select("Online Purchases")    
:- module(zara_ssh_tools,
          [ ssh_tool/4
          ]).

ssh_tool('hosts', 'ssh:hosts', 'ssh.hosts', read).
ssh_tool('file_stat', 'ssh:file-stat', 'ssh.file.stat', read).
ssh_tool('file_list', 'ssh:file-list', 'ssh.file.list', read).
ssh_tool('file_fetch', 'ssh:file-fetch', 'ssh.file.fetch', write).

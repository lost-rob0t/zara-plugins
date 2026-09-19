:- module(zara_music_tools,
          [ music_tool/4,
            music_strategy/1,
            music_requires_current_track/1,
            music_transport_capability/2
          ]).

music_tool('current', 'music:current', 'music.current', read).
music_tool('search', 'music:search', 'music.search', read).
music_tool('recommend', 'music:recommend', 'music.recommend', read).
music_tool('play', 'music:play', 'music.play', write).
music_tool('pause', 'music:pause', 'music.pause', write).
music_tool('volume', 'music:volume', 'music.volume', write).
music_tool('favorite_current', 'music:favorite-current', 'music.favorite.current', write).
music_tool('playlist_add_current', 'music:playlist-add-current', 'music.playlist.add_current', write).

music_strategy(familiar).
music_strategy(discovery).
music_strategy(rediscovery).
music_strategy(similar).
music_strategy(era).
music_strategy(mood).
music_strategy('deep-cut').
music_strategy('album-flow').
music_strategy('sonic-path').

music_requires_current_track('music:favorite-current').
music_requires_current_track('music:playlist-add-current').

music_transport_capability(remote_ssh, 'ssh.file.fetch').

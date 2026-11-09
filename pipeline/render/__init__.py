"""Render: turn locked Echoes inputs into the finished video.

echoes_captions.py renders the HyperFrames karaoke captions at 24 fps
(the caption project itself is still to be ported — see that script).
echoes_assemble.py trims and concats the locked clips, composites the
captions, and does the cinema finish (two-pass loudnorm -23 LUFS).
"""

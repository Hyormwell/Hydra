from hydra_reposter.core.errors import FloodWaitSoft, FloodWaitHard, PeerFlood

def test_floodwait_subclasses():
    err = FloodWaitSoft(30)
    assert isinstance(err, FloodWaitSoft)
    assert isinstance(err, FloodWaitHard) is False
    assert err.wait_seconds == 30
    assert "30s" in str(err)

def test_peerflood_is_reposter_error():
    from hydra_reposter.core.errors import ReposterError
    assert issubclass(PeerFlood, ReposterError)
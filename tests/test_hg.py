import copy
import imp
import mock
import os
import pytest

mozphab = imp.load_source(
    "mozphab", os.path.join(os.path.dirname(__file__), os.path.pardir, "moz-phab")
)


@mock.patch("mozphab.Mercurial.hg_out")
def test_get_successor(m_hg_hg_out, hg):
    m_hg_hg_out.return_value = []
    assert (None, None) == hg._get_successor("x")

    m_hg_hg_out.return_value = ["1 abcde"]
    assert ["1", "abcde"] == hg._get_successor("x")

    m_hg_hg_out.return_value = ["a", "b"]
    with pytest.raises(mozphab.Error):
        hg._get_successor("x")


@mock.patch("mozphab.Mercurial._get_successor")
@mock.patch("mozphab.Mercurial.rebase_commit")
@mock.patch("mozphab.Mercurial._get_parent")
@mock.patch("mozphab.Mercurial._find_forks_to_rebase")
def test_finalize(m_hg_find_forks, m_get_parent, m_hg_rebase, m_hg_get_successor, hg):
    commits = [
        {"rev": "1", "node": "aaa", "orig-node": "aaa"},
        {"rev": "2", "node": "bbb", "orig-node": "bbb"},
        {"rev": "3", "node": "ccc", "orig-node": "ccc"},
    ]

    m_hg_find_forks.return_value = []
    m_get_parent.return_value = "different:than_others"
    m_hg_get_successor.return_value = (None, None)
    hg.finalize(copy.deepcopy(commits))
    assert m_hg_rebase.call_count == 2
    assert m_hg_rebase.call_args_list == [
        mock.call(
            {"rev": "2", "node": "bbb", "orig-node": "bbb"},
            {"rev": "1", "node": "aaa", "orig-node": "aaa"},
        ),
        mock.call(
            {"rev": "3", "node": "ccc", "orig-node": "ccc"},
            {"rev": "2", "node": "bbb", "orig-node": "bbb"},
        ),
    ]

    m_get_parent.side_effect = ("first", "aaa", "last")
    m_hg_rebase.reset_mock()
    hg.finalize(commits)
    m_hg_rebase.assert_called_once_with(
        {"rev": "3", "node": "ccc", "orig-node": "ccc"},
        {"rev": "2", "node": "bbb", "orig-node": "bbb"},
    )

    m_hg_get_successor.reset_mock()
    m_get_parent.side_effect = None
    m_get_parent.return_value = "different:than_others"
    m_hg_get_successor.side_effect = [(None, None), ("4", "ddd")]
    _commits = commits[:]
    hg.finalize(_commits)
    assert m_hg_get_successor.call_count == 2
    assert m_hg_get_successor.call_args_list == [mock.call("bbb"), mock.call("ccc")]
    assert _commits == [
        {"rev": "1", "node": "aaa", "orig-node": "aaa"},
        {"rev": "2", "node": "bbb", "orig-node": "bbb"},
        {"rev": "3", "node": "ddd", "orig-node": "ccc", "name": "4:ddd"},
    ]

    m_hg_rebase.reset_mock()
    m_hg_get_successor.side_effect = None
    m_hg_get_successor.return_value = (None, None)
    m_hg_find_forks.side_effect = (["XXX"], [], [])
    _commits = commits[:]
    _commits[0]["node"] = "AAA"  # node has been amended
    hg.finalize(_commits)
    assert m_hg_rebase.call_count == 3


@mock.patch("mozphab.Mercurial.rebase_commit")
def test_finalize_no_evolve(m_hg_rebase, hg):
    hg.use_evolve = False
    hg.finalize([dict(rev="1", node="aaa"), dict(rev="2", node="bbb")])
    assert m_hg_rebase.not_called()


def test_find_forks(hg):
    original_nodes = ["aaa", "bbb", "ccc", "ddd", "eee"]

    # "aaa" amended, "bbb" in commit stack (but not amended), "xxx" is a fork
    commit = {"node": "AAA", "orig-node": "aaa", "children": ["bbb", "xxx"]}
    assert ["xxx"] == hg._find_forks_to_rebase(commit, original_nodes)
    # "bbb" not amended, "yyy" is a fork
    commit = {"node": "bbb", "orig-node": "bbb", "children": ["ccc", "yyy"]}
    assert [] == hg._find_forks_to_rebase(commit, original_nodes)
    # "ccc" amended, "ddd" in commit stack, "zzz" is a fork
    commit = {"node": "CCC", "orig-node": "ccc", "children": ["ddd", "zzz"]}
    assert ["zzz"] == hg._find_forks_to_rebase(commit, original_nodes)
    # "ddd" amended, no forks found
    commit = {"node": "DDD", "orig-node": "ddd", "children": ["eee"]}
    assert [] == hg._find_forks_to_rebase(commit, original_nodes)
    # "eee" amended, no children
    commit = {"node": "EEE", "orig-node": "eee", "children": []}
    assert [] == hg._find_forks_to_rebase(commit, original_nodes)


@mock.patch("mozphab.config")
@mock.patch("mozphab.parse_config")
@mock.patch("mozphab.Mercurial.hg_out")
@mock.patch("mozphab.Mercurial.hg_log")
def test_set_args(m_hg_hg_log, m_hg_hg_out, m_parse_config, m_config, hg):
    class Args:
        def __init__(self, start="(auto)", end=".", safe_mode=False):
            self.start_rev = start
            self.end_rev = end
            self.safe_mode = safe_mode

    with pytest.raises(mozphab.Error):
        hg.set_args(Args())

    hg._hg = []
    m_config.safe_mode = False
    m_parse_config.return_value = {"ui.username": "username", "extensions.evolve": ""}
    hg.set_args(Args())
    assert ["--config", "extensions.rebase="] == hg._hg
    assert hg.use_evolve == True
    assert hg.has_shelve == False

    # safe_mode
    safe_mode_options = (
        ["--config", "extensions.rebase="]
        + ["--config", "ui.username=username"]
        + ["--config", "extensions.evolve="]
    )
    hg._hg = []
    hg.set_args(Args(safe_mode=True))
    assert safe_mode_options == hg._hg

    m_config.safe_mode = True
    hg._hg = []
    hg.set_args(Args())
    assert safe_mode_options == hg._hg

    # no evolve
    m_config.safe_mode = False
    hg._hg = []
    m_parse_config.return_value = {"ui.username": "username", "extensions.shelve": ""}
    hg.set_args(Args())
    assert (
        ["--config", "extensions.rebase="]
        + ["--config", "experimental.evolution.createmarkers=true"]
        + ["--config", "extensions.strip="]
    ) == hg._hg
    assert hg.use_evolve == False
    assert hg.has_shelve == True

    m_hg_hg_log.side_effect = [("1234567890123",), ("0987654321098",)]
    hg.set_args(Args())
    assert "123456789012::098765432109" == hg.revset

    m_hg_hg_log.side_effect = IndexError
    with pytest.raises(mozphab.Error):
        hg.set_args(Args())

$gwx1_XC_5 = function(_, _v, _n, _p, _s, _wp, _wl, $gwn, $gwl, $gwh, wh, $gstack, $gwrt, gra, grb, TestTest, wfor, _ca, _da, _r, _rz, _o, _oz, _1, _1z, _2, _2z, _m, _mz, nv_getDate, nv_getRegExp, nv_console, nv_parseInt, nv_parseFloat, nv_isNaN, nv_isFinite, nv_decodeURI, nv_decodeURIComponent, nv_encodeURI, nv_encodeURIComponent, $gdc, nv_JSON, _af, _gv, _ai, _grp, _gd, _gapi, $ixc, _ic, _w, _ev, _tsd) {
    return function(path, global) {
        if (typeof global === 'undefined') {
            if (typeof __GWX_GLOBAL__ === 'undefined') global = {};
            else global = __GWX_GLOBAL__;
        }
        if (typeof __WXML_GLOBAL__ === 'undefined') {
            __WXML_GLOBAL__ = {};
        }
        __WXML_GLOBAL__.modules = __WXML_GLOBAL__.modules || {};
        var e_ = {}
        if (typeof(global.entrys) === 'undefined') global.entrys = {};
        e_ = global.entrys;
        var d_ = {}
        if (typeof(global.defines) === 'undefined') global.defines = {};
        d_ = global.defines;
        var f_ = {}
        if (typeof(global.modules) === 'undefined') global.modules = {};
        f_ = global.modules || {};
        var p_ = {}
        __WXML_GLOBAL__.ops_cached = __WXML_GLOBAL__.ops_cached || {}
        __WXML_GLOBAL__.ops_set = __WXML_GLOBAL__.ops_set || {};
        __WXML_GLOBAL__.ops_init = __WXML_GLOBAL__.ops_init || {};
        var z = __WXML_GLOBAL__.ops_set.$gwx1_XC_5 || [];

        function gz$gwx1_XC_5_1() {
            if (__WXML_GLOBAL__.ops_cached.$gwx1_XC_5_1) return __WXML_GLOBAL__.ops_cached.$gwx1_XC_5_1
            __WXML_GLOBAL__.ops_cached.$gwx1_XC_5_1 = [];
            (function(z) {
                var a = 11;

                function Z(ops) {
                    z.push(ops)
                }
                Z([3, 'invitation data-v-6744d14a'])
                Z([
                    [2, '+'],
                    [
                        [2, '+'],
                        [
                            [2, '+'],
                            [1, 'color:'],
                            [
                                [6],
                                [
                                    [6],
                                    [
                                        [7],
                                        [3, 'user']
                                    ],
                                    [3, 'color']
                                ],
                                [3, 'colText']
                            ]
                        ],
                        [1, ';']
                    ],
                    [
                        [2, '+'],
                        [
                            [2, '+'],
                            [1, 'background:'],
                            [
                                [6],
                                [
                                    [6],
                                    [
                                        [7],
                                        [3, 'user']
                                    ],
                                    [3, 'color']
                                ],
                                [3, 'colBg']
                            ]
                        ],
                        [1, ';']
                    ]
                ])
                Z([3, '__l'])
                Z([3, 'data-v-6744d14a'])
                Z([1, true])
                Z([3, '43c03d0b-1'])
                Z(z[2])
                Z([3, 'data-v-6744d14a vue-ref'])
                Z([
                    [7],
                    [3, 'shareData']
                ])
                Z([3, 'tipTool'])
                Z(z[4])
                Z([3, '43c03d0b-2'])
                Z([
                    [2, '=='],
                    [
                        [7],
                        [3, 'curNow']
                    ],
                    [1, 0]
                ])
                Z([
                    [2, '=='],
                    [
                        [7],
                        [3, 'curNow']
                    ],
                    [1, 1]
                ])
            })(__WXML_GLOBAL__.ops_cached.$gwx1_XC_5_1);
            return __WXML_GLOBAL__.ops_cached.$gwx1_XC_5_1
        }
        __WXML_GLOBAL__.ops_set.$gwx1_XC_5 = z;
        __WXML_GLOBAL__.ops_init.$gwx1_XC_5 = true;
        var x = ['./userPages/myInvitation/myInvitation.wxml'];
        d_[x[0]] = {}
        var m0 = function(e, s, r, gg) {
            var z = gz$gwx1_XC_5_1()
            var lCB = _mz(z, 'view', ['class', 0, 'style', 1], [], e, s, gg)
            var eFB = _mz(z, 'qs-nav-bar', ['bind:__l', 2, 'class', 1, 'type', 2, 'vueId', 3], [], e, s, gg)
            _(lCB, eFB)
            var bGB = _mz(z, 'qs-tip-tool', ['bind:__l', 6, 'class', 1, 'data', 2, 'data-ref', 3, 'isShow', 4, 'vueId', 5], [], e, s, gg)
            _(lCB, bGB)
            var aDB = _v()
            _(lCB, aDB)
            if (_oz(z, 12, e, s, gg)) {
                aDB.wxVkey = 1
            }
            var tEB = _v()
            _(lCB, tEB)
            if (_oz(z, 13, e, s, gg)) {
                tEB.wxVkey = 1
            }
            aDB.wxXCkey = 1
            tEB.wxXCkey = 1
            _(r, lCB)
            return r
        }
        e_[x[0]] = {
            f: m0,
            j: [],
            i: [],
            ti: [],
            ic: []
        }
        if (path && e_[path]) {
            return function(env, dd, global) {
                $gwxc = 0;
                var root = {
                    "tag": "wx-page"
                };
                root.children = [];
                g = "$gwx1_XC_5";
                var main = e_[path].f
                if (typeof global === "undefined") global = {};
                global.f = $gdc(f_[path], "", 1);
                try {
                    main(env, {}, root, global);
                    _tsd(root)
                } catch (err) {
                    console.log(err)
                };
                g = "";
                return root;
            }
        }
    }
}(__g.a, __g.b, __g.c, __g.d, __g.e, __g.f, __g.g, __g.h, __g.i, __g.j, __g.k, __g.l, __g.m, __g.n, __g.o, __g.p, __g.q, __g.r, __g.s, __g.t, __g.u, __g.v, __g.w, __g.x, __g.y, __g.z, __g.A, __g.B, __g.C, __g.D, __g.E, __g.F, __g.G, __g.H, __g.I, __g.J, __g.K, __g.L, __g.M, __g.N, __g.O, __g.P, __g.Q, __g.R, __g.S, __g.T, __g.U, __g.V, __g.W, __g.X, __g.Y, __g.Z, __g.aa);
if (__vd_version_info__.delayedGwx || false) $gwx1_XC_5();
if (__vd_version_info__.delayedGwx) __wxAppCode__['userPages/myInvitation/myInvitation.wxml'] = [$gwx1_XC_5, './userPages/myInvitation/myInvitation.wxml'];
else __wxAppCode__['userPages/myInvitation/myInvitation.wxml'] = $gwx1_XC_5('./userPages/myInvitation/myInvitation.wxml');;
__wxRoute = "userPages/myInvitation/myInvitation";
__wxRouteBegin = true;
__wxAppCurrentFile__ = "userPages/myInvitation/myInvitation.js";
define("userPages/myInvitation/myInvitation.js", function(require, module, exports, window, document, frames, self, location, navigator, localStorage, history, Caches, screen, alert, confirm, prompt, XMLHttpRequest, WebSocket, Reporter, webkit, WeixinJSCore) {
    "use strict";
    (global.webpackJsonp = global.webpackJsonp || []).push([
        ["userPages/myInvitation/myInvitation"], {
            "0d9a": function(t, e, n) {
                (function(t) {
                    var a = n("47a9");
                    Object.defineProperty(e, "__esModule", {
                        value: !0
                    }), e.default = void 0;
                    var r = a(n("7eb4")),
                        o = a(n("ee10")),
                        i = n("d604"),
                        c = {
                            mixins: [a(n("ab67")).default],
                            data: function() {
                                return {
                                    curNow: 0,
                                    shareData: {
                                        type: "shareData",
                                        shortLink: "",
                                        urlLink: "",
                                        QR: ""
                                    }
                                }
                            },
                            mounted: function() {
                                this.loadData()
                            },
                            methods: {
                                loadData: function() {
                                    this.$store.dispatch("getShare")
                                },
                                getNote: function() {
                                    var e = this;
                                    return (0, o.default)(r.default.mark((function n() {
                                        var a;
                                        return r.default.wrap((function(n) {
                                            for (;;) switch (n.prev = n.next) {
                                                case 0:
                                                    return a = e, n.prev = 1, t.showLoading({
                                                        title: "数据加载中..."
                                                    }), n.next = 5, a.getShortLink();
                                                case 5:
                                                    if (!e.user.qrImg[1]) {
                                                        n.next = 9;
                                                        break
                                                    }
                                                    e.shareData.QR = e.user.qrImg[1], n.next = 11;
                                                    break;
                                                case 9:
                                                    return n.next = 11, a.getQR();
                                                case 11:
                                                    (0, i.getURLLink)({
                                                        path: "pages/tendency/tendency",
                                                        query: "shareId=".concat(a.user.info.id)
                                                    }).then((function(t) {
                                                        var e;
                                                        try {
                                                            e = a.$DEC(t.data.data.encryptedData).data
                                                        } catch (n) {
                                                            e = t.data
                                                        }
                                                        if (console.log("getURLLink 数据", t), !e) throw new Error;
                                                        a.shareData.urlLink = e, a.showTip({
                                                            date: a.$dayjs(new Date),
                                                            link: "https://docs.qq.com/doc/DYmV6amN0dktqd1dF",
                                                            title: "专属链接",
                                                            content: "\n\t\t\t\t\t\t\t<p>您的专属链接如下：</p><br/>\n\t\t\t\t\t\t\t<p>1、短链，</p>\n\t\t\t\t\t\t\t<p>".concat(a.shareData.shortLink, "</p>\n\t\t\t\t\t\t\t<p>用于群聊、公众号、朋友圈</p><br/>\n\t\t\t\t\t\t\t<p>2、http外链</p>\n\t\t\t\t\t\t\t<p>").concat(a.shareData.urlLink, '</p>\n\t\t\t\t\t\t\t<p>用于站外跳转</p><br/>\n\t\t\t\t\t\t\t<p>3、专属二维码</p>\n\t\t\t\t\t\t\t<img style="weight:12rem;height:12rem" src="').concat(a.shareData.QR, '"/><br/><br/>\n\t\t\t\t\t\t\t<p>邀请用户下单时，自动结算20%佣金到微信钱包。</p><br/>\n\t\t\t\t\t\t\t<p>“拉新”分佣形式不限于以上三种，</p>\n\t\t\t\t\t\t\t<p>还包含转发小卡片、截图直达等方式，</p>\n\t\t\t\t\t\t\t<p>点击“展开更多”查看分佣机制。</p>\n\t\t\t\t\t\t')
                                                        })
                                                    })).catch((function(t) {
                                                        console.log("getURLLink 错误", t)
                                                    })).finally((function() {
                                                        return t.hideLoading()
                                                    })), n.next = 18;
                                                    break;
                                                case 14:
                                                    n.prev = 14, n.t0 = n.catch(1), t.hideLoading(), console.log("短链/菊花码/URL错误", n.t0);
                                                case 18:
                                                case "end":
                                                    return n.stop()
                                            }
                                        }), n, null, [
                                            [1, 14]
                                        ])
                                    })))()
                                },
                                getShortLink: function() {
                                    var t = this,
                                        e = encodeURIComponent(JSON.stringify({
                                            asset: t.user.global.defalutAssetId,
                                            group: t.user.global.defalutGroupId,
                                            variety: t.user.global.defalutTmId,
                                            shareId: t.user.info.id
                                        }));
                                    return new Promise((function(n, a) {
                                        (0, i.getShortLink)({
                                            pageUrl: "pages/tendency/tendency?object=".concat(e)
                                        }).then((function(e) {
                                            var a;
                                            try {
                                                a = t.$DEC(e.data.data.encryptedData).data
                                            } catch (t) {
                                                a = e.data
                                            }
                                            if (console.log("getShortLink 数据", e), !a) throw new Error;
                                            t.shareData.shortLink = a, n()
                                        })).catch((function(t) {
                                            console.log("getShortLink 错误", t), a()
                                        }))
                                    }))
                                },
                                getQR: function() {
                                    var t = this,
                                        e = {
                                            pageUrl: "pages/tendency/tendency",
                                            sense: "shareId=".concat(this.user.info.id),
                                            style: this.user.info.colorId,
                                            lineColor: this.user.color.colText,
                                            bgColor: this.user.color.colBg
                                        };
                                    return new Promise((function(n, a) {
                                        (0, i.getQrCode)(e).then((function(e) {
                                            var a;
                                            try {
                                                a = t.$DEC(e.data.data.encryptedData).data
                                            } catch (t) {
                                                a = e.data
                                            }
                                            if (console.log("getQrCode 数据", e), !a) throw new Error;
                                            t.shareData.QR = "data:image/jpeg;base64," + e.data, e.data.length > 150 && t.$store.commit("setQrImg", {
                                                index: t.user.info.colorId - 1,
                                                info: "data:image/jpeg;base64," + e.data
                                            }), n()
                                        })).catch((function(t) {
                                            console.log("getQrCode 错误", t), a()
                                        }))
                                    }))
                                },
                                showTip: function(t) {
                                    var e = this.$refs.tipTool;
                                    e.date = this.$dayjs(t.date).format("YYYY/MM/DD"), e.link = t.link, e.title = t.title, e.content = "<p>".concat(t.content, "</p>"), e.open()
                                }
                            }
                        };
                    e.default = c
                }).call(this, n("df3c").default)
            },
            "0e82": function(t, e, n) {
                n.r(e);
                var a = n("0d9a"),
                    r = n.n(a);
                for (var o in a)["default"].indexOf(o) < 0 && function(t) {
                    n.d(e, t, (function() {
                        return a[t]
                    }))
                }(o);
                e.default = r.a
            },
            "2dbf": function(t, e, n) {},
            "339d": function(t, e, n) {
                var a = n("2dbf");
                n.n(a).a
            },
            c378: function(t, e, n) {
                n.d(e, "b", (function() {
                    return r
                })), n.d(e, "c", (function() {
                    return o
                })), n.d(e, "a", (function() {
                    return a
                }));
                var a = {
                        qsNavBar: function() {
                            return n.e("components/navBar/navBar").then(n.bind(null, "0adc"))
                        },
                        qsTipTool: function() {
                            return n.e("components/tipTool/tipTool").then(n.bind(null, "46c1"))
                        }
                    },
                    r = function() {
                        var t = this,
                            e = (t.$createElement, t._self._c, 0 == t.curNow ? t.user.share[1].length : null),
                            n = 0 == t.curNow && e ? t.__map(t.user.share[1], (function(e, n) {
                                return {
                                    $orig: t.__get_orig(e),
                                    g1: t.$dayjs(e.loginDate).format("YYYY/MM/DD"),
                                    g2: t.$dayjs(e.loginDate).format("HH:mm:ss")
                                }
                            })) : null,
                            a = 1 == t.curNow ? t.user.share[3].length : null,
                            r = 1 == t.curNow && a ? t.__map(t.user.share[3], (function(e, n) {
                                return {
                                    $orig: t.__get_orig(e),
                                    g4: t.$dayjs(e.finishTime).format("YYYY/MM/DD")
                                }
                            })) : null;
                        t._isMounted || (t.e0 = function(e) {
                            t.curNow = 0
                        }, t.e1 = function(e) {
                            t.curNow = 1
                        }), t.$mp.data = Object.assign({}, {
                            $root: {
                                g0: e,
                                l0: n,
                                g3: a,
                                l1: r
                            }
                        })
                    },
                    o = []
            },
            ef05: function(t, e, n) {
                n.r(e);
                var a = n("c378"),
                    r = n("0e82");
                for (var o in r)["default"].indexOf(o) < 0 && function(t) {
                    n.d(e, t, (function() {
                        return r[t]
                    }))
                }(o);
                n("339d");
                var i = n("828b"),
                    c = Object(i.a)(r.default, a.b, a.c, !1, null, "6744d14a", null, !1, a.a, void 0);
                e.default = c.exports
            },
            efb4: function(t, e, n) {
                (function(t, e) {
                    var a = n("47a9");
                    n("5a31"), a(n("3240"));
                    var r = a(n("ef05"));
                    t.__webpack_require_UNI_MP_PLUGIN__ = n, e(r.default)
                }).call(this, n("3223").default, n("df3c").createPage)
            }
        },
        [
            ["efb4", "common/runtime", "common/vendor"]
        ]
    ]);
}, {
    isPage: true,
    isComponent: true,
    currentFile: 'userPages/myInvitation/myInvitation.js'
});
require("userPages/myInvitation/myInvitation.js");
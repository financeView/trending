$gwx1_XC_2 = function(_, _v, _n, _p, _s, _wp, _wl, $gwn, $gwl, $gwh, wh, $gstack, $gwrt, gra, grb, TestTest, wfor, _ca, _da, _r, _rz, _o, _oz, _1, _1z, _2, _2z, _m, _mz, nv_getDate, nv_getRegExp, nv_console, nv_parseInt, nv_parseFloat, nv_isNaN, nv_isFinite, nv_decodeURI, nv_decodeURIComponent, nv_encodeURI, nv_encodeURIComponent, $gdc, nv_JSON, _af, _gv, _ai, _grp, _gd, _gapi, $ixc, _ic, _w, _ev, _tsd) {
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
        var z = __WXML_GLOBAL__.ops_set.$gwx1_XC_2 || [];

        function gz$gwx1_XC_2_1() {
            if (__WXML_GLOBAL__.ops_cached.$gwx1_XC_2_1) return __WXML_GLOBAL__.ops_cached.$gwx1_XC_2_1
            __WXML_GLOBAL__.ops_cached.$gwx1_XC_2_1 = [];
            (function(z) {
                var a = 11;

                function Z(ops) {
                    z.push(ops)
                }
                Z([3, '__l'])
                Z([3, 'data-v-158c5dff'])
                Z([1, true])
                Z([3, 'd5fa4992-1'])
            })(__WXML_GLOBAL__.ops_cached.$gwx1_XC_2_1);
            return __WXML_GLOBAL__.ops_cached.$gwx1_XC_2_1
        }
        __WXML_GLOBAL__.ops_set.$gwx1_XC_2 = z;
        __WXML_GLOBAL__.ops_init.$gwx1_XC_2 = true;
        var x = ['./userPages/myDeduction/myDeduction.wxml'];
        d_[x[0]] = {}
        var m0 = function(e, s, r, gg) {
            var z = gz$gwx1_XC_2_1()
            var t1 = _mz(z, 'qs-nav-bar', ['bind:__l', 0, 'class', 1, 'type', 1, 'vueId', 2], [], e, s, gg)
            _(r, t1)
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
                g = "$gwx1_XC_2";
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
if (__vd_version_info__.delayedGwx || false) $gwx1_XC_2();
if (__vd_version_info__.delayedGwx) __wxAppCode__['userPages/myDeduction/myDeduction.wxml'] = [$gwx1_XC_2, './userPages/myDeduction/myDeduction.wxml'];
else __wxAppCode__['userPages/myDeduction/myDeduction.wxml'] = $gwx1_XC_2('./userPages/myDeduction/myDeduction.wxml');;
__wxRoute = "userPages/myDeduction/myDeduction";
__wxRouteBegin = true;
__wxAppCurrentFile__ = "userPages/myDeduction/myDeduction.js";
define("userPages/myDeduction/myDeduction.js", function(require, module, exports, window, document, frames, self, location, navigator, localStorage, history, Caches, screen, alert, confirm, prompt, XMLHttpRequest, WebSocket, Reporter, webkit, WeixinJSCore) {
    "use strict";
    (global.webpackJsonp = global.webpackJsonp || []).push([
        ["userPages/myDeduction/myDeduction"], {
            "1b2a": function(t, n, e) {},
            "4cea": function(t, n, e) {
                e.r(n);
                var i = e("6fff"),
                    o = e("4cff");
                for (var u in o)["default"].indexOf(u) < 0 && function(t) {
                    e.d(n, t, (function() {
                        return o[t]
                    }))
                }(u);
                e("9600");
                var a = e("828b"),
                    r = Object(a.a)(o.default, i.b, i.c, !1, null, "158c5dff", null, !1, i.a, void 0);
                n.default = r.exports
            },
            "4cff": function(t, n, e) {
                e.r(n);
                var i = e("7330"),
                    o = e.n(i);
                for (var u in i)["default"].indexOf(u) < 0 && function(t) {
                    e.d(n, t, (function() {
                        return i[t]
                    }))
                }(u);
                n.default = o.a
            },
            "6fff": function(t, n, e) {
                e.d(n, "b", (function() {
                    return o
                })), e.d(n, "c", (function() {
                    return u
                })), e.d(n, "a", (function() {
                    return i
                }));
                var i = {
                        qsNavBar: function() {
                            return e.e("components/navBar/navBar").then(e.bind(null, "0adc"))
                        }
                    },
                    o = function() {
                        var t = this,
                            n = (t.$createElement, t._self._c, t.list.length),
                            e = n ? t.__map(t.list, (function(n, e) {
                                return {
                                    $orig: t.__get_orig(n),
                                    g1: t.$dayjs(n.date).format("YYYY/MM/DD")
                                }
                            })) : null;
                        t.$mp.data = Object.assign({}, {
                            $root: {
                                g0: n,
                                l0: e
                            }
                        })
                    },
                    u = []
            },
            7330: function(t, n, e) {
                var i = e("47a9");
                Object.defineProperty(n, "__esModule", {
                    value: !0
                }), n.default = void 0;
                var o = {
                    mixins: [i(e("ab67")).default],
                    data: function() {
                        return {
                            list: []
                        }
                    },
                    mounted: function() {
                        this.getList()
                    },
                    methods: {
                        getList: function() {
                            var t = this;
                            this.list = [];
                            for (var n = 0; n < this.user.coupon.giftList.length; n++) this.list.push({
                                title: "领取“" + this.user.coupon.giftList[n].couponTheme + "”",
                                date: this.user.coupon.giftList[n].receiveDate,
                                money: this.user.coupon.giftList[n].couponAmount,
                                type: 0
                            });
                            for (var e = 0; e < this.user.coupon.paidList.length; e++) this.list.push({
                                title: "购买“" + this.user.coupon.paidList[e].couponTheme + "”",
                                date: this.user.coupon.paidList[e].receiveDate,
                                money: this.user.coupon.paidList[e].couponAmount,
                                type: 1
                            });
                            this.list.sort((function(n, e) {
                                return t.$dayjs(n.date).isBefore(t.$dayjs(e.date)) ? 1 : -1
                            }))
                        }
                    }
                };
                n.default = o
            },
            9600: function(t, n, e) {
                var i = e("1b2a");
                e.n(i).a
            },
            b3b7: function(t, n, e) {
                (function(t, n) {
                    var i = e("47a9");
                    e("5a31"), i(e("3240"));
                    var o = i(e("4cea"));
                    t.__webpack_require_UNI_MP_PLUGIN__ = e, n(o.default)
                }).call(this, e("3223").default, e("df3c").createPage)
            }
        },
        [
            ["b3b7", "common/runtime", "common/vendor"]
        ]
    ]);
}, {
    isPage: true,
    isComponent: true,
    currentFile: 'userPages/myDeduction/myDeduction.js'
});
require("userPages/myDeduction/myDeduction.js");
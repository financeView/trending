$gwx1_XC_3 = function(_, _v, _n, _p, _s, _wp, _wl, $gwn, $gwl, $gwh, wh, $gstack, $gwrt, gra, grb, TestTest, wfor, _ca, _da, _r, _rz, _o, _oz, _1, _1z, _2, _2z, _m, _mz, nv_getDate, nv_getRegExp, nv_console, nv_parseInt, nv_parseFloat, nv_isNaN, nv_isFinite, nv_decodeURI, nv_decodeURIComponent, nv_encodeURI, nv_encodeURIComponent, $gdc, nv_JSON, _af, _gv, _ai, _grp, _gd, _gapi, $ixc, _ic, _w, _ev, _tsd) {
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
        var z = __WXML_GLOBAL__.ops_set.$gwx1_XC_3 || [];

        function gz$gwx1_XC_3_1() {
            if (__WXML_GLOBAL__.ops_cached.$gwx1_XC_3_1) return __WXML_GLOBAL__.ops_cached.$gwx1_XC_3_1
            __WXML_GLOBAL__.ops_cached.$gwx1_XC_3_1 = [];
            (function(z) {
                var a = 11;

                function Z(ops) {
                    z.push(ops)
                }
                Z([3, '__l'])
                Z([3, 'data-v-11a3516c'])
                Z([1, true])
                Z([3, 'cb87cdae-1'])
            })(__WXML_GLOBAL__.ops_cached.$gwx1_XC_3_1);
            return __WXML_GLOBAL__.ops_cached.$gwx1_XC_3_1
        }
        __WXML_GLOBAL__.ops_set.$gwx1_XC_3 = z;
        __WXML_GLOBAL__.ops_init.$gwx1_XC_3 = true;
        var x = ['./userPages/myInformation/myInformation.wxml'];
        d_[x[0]] = {}
        var m0 = function(e, s, r, gg) {
            var z = gz$gwx1_XC_3_1()
            var b3 = _mz(z, 'qs-nav-bar', ['bind:__l', 0, 'class', 1, 'type', 1, 'vueId', 2], [], e, s, gg)
            _(r, b3)
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
                g = "$gwx1_XC_3";
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
if (__vd_version_info__.delayedGwx || false) $gwx1_XC_3();
if (__vd_version_info__.delayedGwx) __wxAppCode__['userPages/myInformation/myInformation.wxml'] = [$gwx1_XC_3, './userPages/myInformation/myInformation.wxml'];
else __wxAppCode__['userPages/myInformation/myInformation.wxml'] = $gwx1_XC_3('./userPages/myInformation/myInformation.wxml');;
__wxRoute = "userPages/myInformation/myInformation";
__wxRouteBegin = true;
__wxAppCurrentFile__ = "userPages/myInformation/myInformation.js";
define("userPages/myInformation/myInformation.js", function(require, module, exports, window, document, frames, self, location, navigator, localStorage, history, Caches, screen, alert, confirm, prompt, XMLHttpRequest, WebSocket, Reporter, webkit, WeixinJSCore) {
    "use strict";
    (global.webpackJsonp = global.webpackJsonp || []).push([
        ["userPages/myInformation/myInformation"], {
            "2a02": function(t, a, e) {
                (function(t) {
                    var n = e("47a9");
                    Object.defineProperty(a, "__esModule", {
                        value: !0
                    }), a.default = void 0;
                    var o = n(e("ab67")),
                        r = e("d604"),
                        i = {
                            mixins: [o.default],
                            data: function() {
                                return {
                                    userForm: {
                                        avatar: "",
                                        nickName: ""
                                    },
                                    nickNameDisabled: !0
                                }
                            },
                            computed: {
                                avatarShow: function() {
                                    return function(t) {
                                        if (String(t).length > 30) return t;
                                        var a = new Date,
                                            e = 10 * Math.floor(a.getTime() / 1e4),
                                            n = "".concat(a.getFullYear()).concat((a.getMonth() + 1).toString().padStart(2, "0")).concat(a.getDate().toString().padStart(2, "0"));
                                        return t ? "".concat("https://www.trendtrader.cn", "/avatar/image/").concat(t, "?t=").concat(e) : "".concat("https://www.trendtrader.cn", "/avatar/icon/注册用户默认头像.png?t=").concat(n)
                                    }
                                },
                                nickNameModel: {get: function() {
                                        return this.nickNameDisabled ? this.user.info.name : this.userForm.nickName
                                    },
                                    set: function(t) {
                                        this.nickNameDisabled || (this.userForm.nickName = t)
                                    }
                                }
                            },
                            mounted: function() {
                                this.userForm = {
                                    avatar: this.user.info.avatarUrl,
                                    nickName: this.user.info.nickName
                                }
                            },
                            methods: {
                                onChooseAvatar: function(a) {
                                    var e = this,
                                        n = a.detail.avatarUrl;
                                    (0, r.upload)({
                                        multipartfile: n,
                                        fileName: e.user.info.id
                                    }).then((function(a) {
                                        var o;
                                        try {
                                            o = e.$DEC(JSON.parse(a.data).data.encryptedData).data
                                        } catch (t) {
                                            o = JSON.parse(a.data).data
                                        }
                                        console.log("upload数据", a), e.userForm.avatar = n, e.$store.commit("setUserAvatar", o), t.showToast({
                                            title: "头像修改成功",
                                            icon: "none"
                                        })
                                    }))
                                },
                                reName: function() {
                                    this.userForm.nickName = this.user.info.name, this.nickNameDisabled = !1
                                },
                                input: function(a) {
                                    a.detail.value.length ? a.detail.value.length > 16 && t.showToast({
                                        title: "昵称长度不能超过16个字符",
                                        icon: "none"
                                    }) : t.showToast({
                                        title: "昵称不能为空",
                                        icon: "none"
                                    }), this.userForm.nickName = a.detail.value
                                },
                                confirmName: function() {
                                    var a = this;
                                    if (!a.userForm.nickName.length || a.userForm.nickName.length > 16) return t.showToast({
                                        title: "格式错误，请检查",
                                        icon: "none"
                                    });
                                    (0, r.updateNew)({
                                        name: a.userForm.nickName,
                                        id: a.user.info.id
                                    }).then((function(e) {
                                        var n, o;
                                        try {
                                            n = a.$DEC(e.data.data.encryptedData).data, o = a.$DEC(e.data.data.encryptedData).msg
                                        } catch (t) {
                                            n = e.data.data, o = e.data.msg
                                        }
                                        if (console.log("updateNew数据", e), !n && !o || "Unauthorized" == o) throw new Error;
                                        t.showToast({
                                            title: o || "",
                                            icon: "success"
                                        }), a.nickNameDisabled = !0, a.$store.commit("setUserName", a.userForm.nickName)
                                    }))
                                },
                                copy: function() {
                                    t.setClipboardData({
                                        data: String(this.user.info.id),
                                        success: function() {
                                            t.showToast({
                                                icon: "success",
                                                title: "复制成功"
                                            })
                                        },
                                        fail: function() {
                                            t.showToast({
                                                icon: "error",
                                                title: "复制失败"
                                            })
                                        }
                                    })
                                }
                            }
                        };
                    a.default = i
                }).call(this, e("df3c").default)
            },
            "2d89": function(t, a, e) {
                e.r(a);
                var n = e("2a02"),
                    o = e.n(n);
                for (var r in n)["default"].indexOf(r) < 0 && function(t) {
                    e.d(a, t, (function() {
                        return n[t]
                    }))
                }(r);
                a.default = o.a
            },
            "33ec": function(t, a, e) {
                e.r(a);
                var n = e("762f"),
                    o = e("2d89");
                for (var r in o)["default"].indexOf(r) < 0 && function(t) {
                    e.d(a, t, (function() {
                        return o[t]
                    }))
                }(r);
                e("98d9");
                var i = e("828b"),
                    c = Object(i.a)(o.default, n.b, n.c, !1, null, "11a3516c", null, !1, n.a, void 0);
                a.default = c.exports
            },
            "4d5a": function(t, a, e) {
                (function(t, a) {
                    var n = e("47a9");
                    e("5a31"), n(e("3240"));
                    var o = n(e("33ec"));
                    t.__webpack_require_UNI_MP_PLUGIN__ = e, a(o.default)
                }).call(this, e("3223").default, e("df3c").createPage)
            },
            "5e0c": function(t, a, e) {},
            "762f": function(t, a, e) {
                e.d(a, "b", (function() {
                    return o
                })), e.d(a, "c", (function() {
                    return r
                })), e.d(a, "a", (function() {
                    return n
                }));
                var n = {
                        qsNavBar: function() {
                            return e.e("components/navBar/navBar").then(e.bind(null, "0adc"))
                        }
                    },
                    o = function() {
                        var t = this,
                            a = (t.$createElement, t._self._c, t.avatarShow(this.userForm.avatar));
                        t._isMounted || (t.e0 = function(a) {
                            t.nickNameDisabled ? t.reName() : t.confirmName()
                        }), t.$mp.data = Object.assign({}, {
                            $root: {
                                m0: a
                            }
                        })
                    },
                    r = []
            },
            "98d9": function(t, a, e) {
                var n = e("5e0c");
                e.n(n).a
            }
        },
        [
            ["4d5a", "common/runtime", "common/vendor"]
        ]
    ]);
}, {
    isPage: true,
    isComponent: true,
    currentFile: 'userPages/myInformation/myInformation.js'
});
require("userPages/myInformation/myInformation.js");
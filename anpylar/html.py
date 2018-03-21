###############################################################################
# Copyright 2018 The AnPyLar Team. All Rights Reserved.
# Use of this source code is governed by an MIT-style license that
# can be found in the LICENSE file at http://anpylar.com/mit-license
###############################################################################

# sys.modules is needed. Importing just _sys which is pure Javascript saves
# some initial loading time

import browser
import browser.html

from . import stacks
from .utils import defaultdict, count
from . import utils
from .observable import Observable

__all__ = []


class render_node(object):
    '''Simple context manager wrapper for managing rendering elements'''
    def __init__(self, node=None):
        self.node = node  # wrapped node to manage in the context

    def __enter__(self):
        node = self.node or stacks.htmlnodes[-1]  # current rendering
        # reappend even if selected to avoid a render_stop from popping it
        stacks.htmlnodes.append(node)
        return node

    def __exit__(self, type_, value, tb):
        if type_ is None:  # no exception raised, do something
            stacks.htmlnodes.pop(-1)
            while _el2render:
                _el2render.pop(-1)._procfuncs()


class _MetaElement(type):
    def __call__(cls, *args, **kwargs):
        # must be intercepted here, because it the link has parameters the
        # object won't be properly stored and retrieved in the HTML element
        rlink = kwargs.pop('routerlink', None)

        compargs = kwargs.pop('_compargs', ())
        compkwargs = kwargs.pop('_compkwargs', {})

        self = super().__call__(*args, **kwargs)  # create
        taglower = getattr(self, 'tagName', '').lower()

        if taglower not in ['script', 'head', 'style']:
            _el2render.append(self)

        if not hasattr(self, '_elparent'):  # flag to avoid overwriting
            self._started = False
            self._elid = next(_ELID)
            self._elparent = stacks.htmlnodes[-1]
            self._rlink = rlink
            self._funcs = defaultdict(list)
            self._dfuncs = defaultdict(list)
            self._sargs = defaultdict(list)
            self._kargs = defaultdict(dict)
            self._txtmplate = None
            self._cvals = dict()  # to cache without polluting space

        # Check if this node already has an active comp
        if self._comp is None:
            if cls._autocomp is None:
                if taglower != 'style':
                    try:
                        self._comp = _comp = self._elparent._comp
                    except AttributeError:
                        self._comp = None
                if taglower != 'router-outlet':
                    # mark for styling
                    try:
                        self.setAttribute(self._comp._get_cid_name(), '')
                    except:
                        pass  # style tag
            else:
                with self:
                    self._comp = cls._autocomp(*compargs, **compkwargs)

                self._comp._renderer(self)
                # if the component is from autocomp and wrapped it has been
                # generated by a visit to a node and not by end-user code,
                # hence the need to issue the call to _load to let it do
                # whatever it needs
                if self._wrapped:
                    self._comp._load()

                # if not wrapped, it has been generated by a call to tagout

            fmtargs = []
            fmtkwargs = {}

            for attr in self.attributes:
                name = attr.name
                value = attr.value
                n0 = name[0]
                if n0 == '(':  # reguest to bind
                    binder = getattr(self._bindx, name[1:-1])
                    lambdize = value[-1] == ')'
                    self._comp._binder(binder, value, lambdize=lambdize)
                elif n0 == '*':
                    binder = getattr(self, name[1:])
                    self._comp._binder(binder, value, lambdize=False)
                elif n0 == '[':
                    name = name[1:-1]
                    if not name:
                        name = value
                    fmtargs.append(name)
                elif n0 == '{':
                    fmtkwargs[name[1:-1]] = value
                elif n0 == '$':
                    binder = getattr(self._bind, name[1:-1])
                    lambdize = value[-1] == ')'
                    self._comp._binder(binder, value, lambdize=lambdize)

            if fmtargs or fmtkwargs:
                self._comp._fmtter(self._fmt, *fmtargs, **fmtkwargs)

        if not self._wrapped:
            if taglower != 'txt':  # anpylar for text templating
                if self._elparent.children:
                    self._elparent <= '\n'  # simulate a real html doc
            self._elparent <= self  # insert in last item ... parent

        if hasattr(self, 'do_customize'):
            do_customize = getattr(self, 'do_customize')
            if do_customize != self:
                self.do_customize(*args, **kwargs)

        return self


class SuperchargedNode(object, metaclass=_MetaElement):
    '''
    The ``SuperchargedNode`` increases the standard powers of a DOM node by
    providing extra methods and being aware of *Observables*, to which it can
    subscribe to react to changes.

    It does also provide supercharged attributes with specially prefixed (and
    suffixed in some cases) attribute names that can provide a small
    programming interface
    '''
    _comp = None
    _autocomp = None

    _TXT = 'text'

    def __enter__(self):
        # auto-created nodes were put there before a component had the
        # chance to parent them, but when rendering a component is in control
        stacks.htmlnodes.append(self)  # self is parent now
        return self

    def __exit__(self, type_, value, traceback):
        stacks.htmlnodes.pop(-1)  # remove itself as parent

    def _ractive(self, status, ractive):
        cl = self.class_name.split()
        if status:
            if ractive not in cl:
                cl.append(ractive)
        else:
            if ractive in cl:
                cl.remove(ractive)

        self.class_name = ' '.join(cl)

    def _procfuncs(self):
        self._started = True
        rlink = self._rlink
        if rlink is None:
            self._rlink = rlink = getattr(self, 'routerlink', None)

        if rlink is not None:
            router = self._comp.router
            if isinstance(rlink, str):
                rl = rlink
                ret = router._routecalc(rl)
                # self.bind('click', lambda x: router.route_to(rl))
                self.bind(
                    'click',
                    lambda x: router.route_to(ret, _recalc=False)
                )
            else:
                rl, kw = rlink  # must be an iterable with 2 itmes
                ret = router._routecalc(rl)
                self.bind(
                    'click',
                    lambda x: router.route_to(ret, _recalc=False, **kw)
                )

            ractive = getattr(self, 'routerlinkactive', None)
            if ractive:
                router._routeregister(ret, self._ractive, ractive)

        if self._txtmplate is None:
            self._txtmplate = getattr(self, self._TXT)

        if not self._txtmplate:
            self._txtmplate = '{}'  # last option

        with render_node(self):
            for k, fl in self._funcs.items():
                for func in fl:
                    func(*self._sargs[k], **self._kargs[k])

    def __call__(self, val, key, ref):
        # A key is needed, hence the explicit mentioning ref too retrieve
        # target arguments
        sargs = self._sargs[key]
        kargs = self._kargs[key]
        # Cache new value
        if isinstance(ref, int):
            sargs[ref] = val
        else:
            kargs[ref] = val

        if not self._started:
            return

        if key in self._funcs:
            fs = self._funcs[key]
        else:
            fs = self._dfuncs[key]

        with render_node(self):
            for f in fs:
                f(*sargs, **kargs)

    def _subintern(self, func, fargs, fkwargs, delay=False):
        key = next(_KEY)
        if not delay:
            self._funcs[key].append(func)
        else:
            self._dfuncs[key].append(func)

        sargs = self._sargs[key]
        for i, sarg in enumerate(fargs, len(sargs)):
            if isinstance(sarg, Observable):
                kw = {'who': self, 'fetch': True}
                # default ref=i to freeze param in lambda during loop
                v = sarg.subscribe(lambda x, ref=i: self(x, key, ref), **kw)
                try:
                    v = v.get_val()
                except AttributeError:
                    v = ''

                sargs.append(v)
            else:
                sargs.append(sarg)

        kargs = self._kargs[key]
        for name, karg in fkwargs.items():
            if isinstance(karg, Observable):
                kw = {'who': self, 'fetch': True}
                v = karg.subscribe(lambda x, ref=name: self(x, key, ref), **kw)
                try:
                    v = v.get_val()
                except AttributeError:
                    v = ''

                kargs[name] = v
            else:
                kargs[name] = karg

        return self

    def _sub(self, func, *args, **kwargs):
        return self._subintern(func, args, kwargs, delay=False)

    def _subdelay(self, func, *args, **kwargs):
        return self._subintern(func, args, kwargs, delay=True)

    def _fmtrecv(self, *args, **kwargs):  # call is in kwargs
        setattr(self, self._TXT, self._txtmplate.format(*args, **kwargs))

    def _fmt(self, *args, **kwargs):
        '''
        Use it as: ``_fmt(*args, **kwargs)``

        Any of the ``args`` or ``kwargs`` can be an observable to which the
        method will automatically subscribe (like for example the observables
        created by *bindings* in components)

        This will format the text field of the tag using the standard *Format
        Mini Language Specification* of Python.

        Any ``arg`` will format the non-named templates ``{}`` sequentially and
        named arguments will target named templates ``{name}``

        When using observables, the formatting will update itself with each new
        value delivered by the observable.
        '''
        return self._sub(self._fmtrecv, *args, **kwargs)

    def _fmtfunc(self, func, *args, **kwargs):
        return self._sub(
            lambda *a, **kw: self._fmtrecv(func(*a, **kw)),
            *args, **kwargs
        )

    @property
    def _render(self):
        '''
        Use it as::

          _render(callbackk, *args, **kwargs)

        Any of the ``args`` or ``kwargs`` can be an observable to which the
        method will automatically subscribe (like for example the observables
        created by *bindings* in components)

        This will call at least one ``callback`` (for the initial rendering
        below the node)

        If any subscription has been made to observable, the rendering will be
        re-done with each new value passed by the observable
        '''
        return _RenderHelper(self)

    def _pub(self, event, *args, **kwargs):
        self.bind(event, lambda evt: self._pubsend(*args, **kwargs))
        return self

    def _pubattr(self, event, attr, *args, **kwargs):
        self.bind(event, lambda evt: self._pubsendattr(attr, *args, **kwargs))
        return self

    def _pubsub(self, event, func, *args, **kwargs):
        self._sub(func, *args, **kwargs)
        return self._pub(event, *args, **kwargs)

    def _pubsend(self, *args, **kwargs):
        val = getattr(self, self._TXT)
        for binding in args:
            binding(val, self)

    def _pubsendattr(self, attr, *args, **kwargs):
        val = getattr(self, attr)
        for binding in args:
            binding(val, self)

    @property
    def _fmtevt(self):
        '''
        Use it as: ``_fmtevt(event, *args, **kwargs)`` or
        ``_fmtevt.event(*args, **kwargs)``

        Any of the ``args`` or ``kwargs`` can be an observable to which the
        method will automatically subscribe (like for example the observables
        created by *bindings* in components)

        This binds a generic event to notify the observables which at the same
        time are using for formatting the content of the tag
        '''
        return _FmtEvtHelper(self)

    @property
    def _fmtvalue(self):
        '''
        Alias: ``_fmtval``

        Use it as: ``_fmtvalue(*args, **kwargs)``

        Any of the ``args`` or ``kwargs`` can be an observable to which the
        method will automatically subscribe (like for example the observables
        created by *bindings* in components)

        This is meant for tags like <input> which have a value field. A binding
        can be passed (just like in _fmt) to format the text in the field.

        At the same time when the value in the field changes the binding will
        be fed with the new value.

        Effectively, this binds the binding bi-directionally for updating the
        field and kicking the observable
        '''
        return _FmtValHelper(self)

    _fmtval = _fmtvalue

    @property
    def _bind(self):
        '''
        Allows binding to an event, with either

          - ``element._bind(event, callback, *args, **kwargs)``

        or

          - ``element._bind.event(callback, *args, **kwargs)``

        The callback will receive the *event* as the first argument as in

          - ``callback(event, *args, **kwargs)``
        '''
        return _BindHelper(self)

    @property
    def _bindx(self):
        '''
        Allows binding to an event, without receiving it in the callback

          - ``element._bindx(event, callback, *args, **kwargs)``

        or

          - ``element._bind.event(callback, *args, **kwargs)``

        The callback will **NOT** receive the *event* as the first argument.

          - ``callback(*args, **kwargs)``
        '''
        return _BindXHelper(self)

    @property
    def _attr(self):
        '''
        Controls the presence/absence of an attribute inside the element

        It can be used as in

          - ``element._attr(name, trigger, on, off)``

        or

          - ``element._attr.name(trigger, on, off)``

        The arguments:

          - ``trigger``: value or observable which controls if ``show`` or
            ``hide`` will be used

          - ``on``: value to activate display of the element

          - ``off``: value to hide the element

        *Note*: if ``on`` and ``off`` are not provided, the defaults will be
         ``"true"`` and ``""`` (empty string)
        '''
        return _AttributeHelper(self)

    @property
    def _style(self):
        '''
        Controls the presence/absence of an attribute inside the element's
        *style*

        It can be used as in

          - ``element._style(name, trigger, on, off)``

        or

          - ``element._style.name(trigger, on, off)``

        The arguments:

          - ``trigger``: value or observable which controls if ``on`` or
            ``off`` will be used

          - ``on``: value to activate display of the element

          - ``off``: value to hide the element

        *Note*: if ``on`` and ``off`` are not provided, the defaults will be
         ``"true"`` and ``""`` (empty string)
        '''
        return _StyleHelper(self)

    def _display(self, trigger, show='', hide='none'):
        '''
        Controls the *display* value inside the *style* on an element.

          - ``trigger``: value or observable which controls if ``show`` or
            ``hide`` will be used

          - ``show`` (default: ''): value to activate display of the element

          - ``hide`` (default: 'none'): value to hide the element

        Returns a reference to the *element*
        '''
        def st(val):
            setattr(self.style, 'display', show if val else hide)

        return self._sub(st, trigger)

    def _display_toggle(self, onoff=None):
        '''
        Toggles/controls the display status of the element

          - ``onoff`` (default: ``None``): if ``None`` the display status will
            be toggled. If either ``True`` or ``False``, the display status
            will be set to on or off respectively

        Returns a reference to the *element*
        '''
        curdisplay = self.style.display

        if onoff is None:  # toggle modus
            if curdisplay is 'none':
                nextdisplay = self._cvals.get('lastdisplay', '')
                if nextdisplay == 'none':
                    nextdisplay = ''
            else:
                nextdisplay = 'none'

            self.style.display = nextdisplay

        elif isinstance(onoff, str):
            self.style.display = onoff
        else:
            if onoff:
                if curdisplay == 'none':
                    self.style.display = self._cvals.get('lastdisplay', '')
            else:
                if curdisplay != 'none':
                    self.style.display = 'none'

        self._cvals['lastdisplay'] = curdisplay
        return self

    @property
    def _class(self):
        '''
        Controls the presence/absence of an attribute inside the element's
        *class*

        It can be used as in

          - ``element._class(name, trigger)``

        or

          - ``element._class.name(trigger)``

        The arguments:

          - ``trigger``: value or observable which controls if ``name`` is part
            of the class or not
        '''
        return _ClassHelper(self)

    @property
    def class_(self):
        '''
        Adds elements to the *class*

        It can be used as in

          - ``element.class_(*args)``

            Each of the args will be added to the *class* attribute. Each arg
            has to be a *string*

        or

          - ``element.class_.name1.name2.``

            *name1* and *name2* will be added to the class.

        Both syntaxes can be mixed:

          - ``element.class_('name1', 'name2').name3

        *Note*: Because ``-`` is not an allowed character in identifiers, ``_``
        can be used and will be changed to ``-``. This is mostly useful for the
        *.attribute* notation
        '''
        return _ClassAddHelper(self)

    @property
    def classless_(self):
        '''
        Removes elements from the *class*

        It can be used as in

          - ``element.classless_(*args)``

            Each of the args will be removed from the *class* attribute. Each
            arg has to be a *string*

        or

          - ``element.classless_.name1.name2.``

            *name1* and *name2* will be removed from the class.

        Both syntaxes can be mixed:

          - ``element.classless_('name1', 'name2').name3``

        *Note*: Because ``-`` is not an allowed character in identifiers, ``_``
        can be used and will be changed to ``-``. This is mostly useful for the
        *.attribute* notation
        '''
        return _ClassRemoveHelper(self)


class _ClassRemoveHelper:
    def __init__(self, target):
        self.target = target

    def __getattr__(self, name):
        name = name.replace('_', '-')
        cparts = self.target.class_name.split()
        try:
            cparts.remove(name)
        except ValueError:
            pass
        else:
            self.target.class_name = ' '.join(cparts)

        return self

    def __call__(self, *args):
        cp = self.target.class_name.split()
        cp.extend(x for x in (a.replace('_', '-') for a in args) if x not in cp)
        self.target.class_name = ' '.join(cp)
        return self.target


class _ClassAddHelper:
    def __init__(self, target):
        self.target = target

    def __getattr__(self, name):
        if self.target.class_name:
            self.target.class_name += ' '

        self.target.class_name += name.replace('_', '-')
        return self

    def __call__(self, *args):
        if self.target.class_name:
            self.target.class_name += ' '

        self.target.class_name += ' '.join(x.replace('_', '-') for x in args)
        return self.target


class _HelperBase:
    helper = None

    def __init__(self, target, helper=None):
        if helper is not None:
            self.helper = helper  # avoid overwriting default values
        self.target = target

    def __getattr__(self, name):
        self.helper = name
        return self


class _BindHelper(_HelperBase):
    def __call__(self, func, *args, **kwargs):
        evt = self.helper
        if evt is None:
            evt = args[0]
            args = args[1:]

        return self.target.bind(evt, lambda e: func(e, *args, **kwargs))


class _BindXHelper(_HelperBase):
    def __call__(self, func, *args, **kwargs):
        evt = self.helper
        if evt is None:
            evt = args[0]
            args = args[1:]

        return self.target.bind(evt, lambda e: func(*args, **kwargs))


class _AttributeHelper(_HelperBase):
    def __call__(self, trigger, on=None, off=None, *args, **kwargs):
        helper = self.helper
        if helper is None:
            helper = trigger
            trigger = on
            on = off
            off = args[0]

        if on is None:
            on = 'true'

        if off is None:
            off = ''

        def st(val, *args, **kwargs):
            stval = on if val else off
            setattr(self.target, helper, stval)

        return self.target._sub(st, trigger)


class _StyleHelper(_HelperBase):
    def __call__(self, trigger, on=None, off=None, *args, **kwargs):
        helper = self.helper
        if helper is None:
            helper = trigger
            trigger = on
            on = off
            off = args[0]

        if on is None:
            on = 'true'

        if off is None:
            off = ''

        def st(val, *args, **kwargs):
            stval = on if val else off
            try:
                setattr(self.target.style, helper, stval)
            except Exception as e:
                pass

        return self.target._sub(st, trigger)


class _DisplayHelper(_HelperBase):
    helper = 'display'

    def __call__(self, trigger, show='', hide='none'):
        def st(val, *args, **kwargs):
            stval = show if val else hide
            setattr(self.target.style, self.helper, stval)

        return self.target._sub(st, trigger)


class _ClassHelper(_HelperBase):
    helper = []

    def __getattr__(self, name):
        self.helper.append(name)
        return self

    def __call__(self, trigger, *args, **kwargs):
        if not self.helper:
            self.helper.append(trigger)
            trigger = args[0]

        return self.target._sub(self._toggle_action, trigger)

    def _toggle_action(self, val):
        cname = self.target.class_name
        cs = cname.split(' ') if cname else []

        for c in self.helper:
            if val:
                if c not in cs:
                    cs.append(c)
            else:
                try:
                    cs.remove(c)
                except ValueError:
                    pass

        self.target.class_name = ' '.join(cs) if cs else ''


class _EvtHelper:
    evt = None

    def __init__(self, target, evt=None):
        self.target = target
        if evt is not None:
            self.evt = evt

    def __getattr__(self, evt):
        self.evt = evt
        return self

    def __call__(self, func, *args, **kwargs):
        return self.target.bind(self.evt, lambda evt: func(*args, **kwargs))

    def bindx(self, func, *args, **kwargs):
        return self.target.bind(self.evt, lambda evt: func(*args, **kwargs))

    def bind(self, func, *args, **kwargs):
        return self.target.bind(self.evt, lambda e: func(e, *args, **kwargs))


class _FmtEvtHelper(_EvtHelper):
    def __call__(self, *args, **kwargs):
        self.target._fmt(*args, **kwargs)
        return self.target._pub(self.evt, *args, **kwargs)


class _FmtValHelper(_FmtEvtHelper):
    evt = 'input'

    def __call__(self, *args, **kwargs):
        self.target._fmt(*args, **kwargs)
        return self.target._pub(self.evt, *args, **kwargs)


class _RenderHelper:
    def __init__(self, target):
        self.target = target
        self._lazy = True

    def __call__(self, func, *args, **kwargs):
        self.func = func
        if not self._lazy:
            return self.target._sub(self._action, *args, **kwargs)

        return self.target._subdelay(self._action, *args, **kwargs)

    def _action(self, *args, **kwargs):
        self.target.clear()
        self.func(*args, **kwargs)

    def __getattr__(self, name):
        if name == 'lazy':
            self._lazy = True
            return self

        return super().__getattr__(name)


def _tout(name, *args, **kwargs):
    try:
        factory = _thismod.tags[name]
    except KeyError:
        factory = _customize_tag(name, True)

    return factory(*args, **kwargs)


def _tagout(name, *args, **kwargs):
    tout = _tout(name.lower(), *args, **kwargs)
    if tout._autocomp is not None:
        tout._comp._load()  # comp was generated, start it
        pass
    return tout


def _routeout(name, *args, **kwargs):
    return _tout(name.lower(), *args, **kwargs)


def _customize_tag(name, dotag=False, component=None):
    lname = name.lower()
    dct = _tagmaps[None].copy()
    dct.update(_tagmaps.get(lname, {}))
    if dotag:
        thetag = browser.html.maketag(name)
    else:
        thetag = getattr(browser.html, name)

    dct['_autocomp'] = component
    try:
        kls = type(lname, (SuperchargedNode, thetag,), dct)
    except TypeError:
        return None

    # lower, Lower and LOWER will be reachable
    for lx in [lname, lname.upper(), lname.capitalize()]:
        setattr(_thismod, lx, kls)
        _thismod.tags[lx] = kls

    return kls


# Prepare custom functions/tags
# Override classes to make them lowercase (readability) and add methods
_thismod = getattr(__BRYTHON__.imported, __name__)

tags = {}  # keep track of all tags

_tag = _tagout

_KEY = utils.count(1)
_ELID = utils.count(1)

document = browser.document

_el2render = []

_tagmaps = {
    None: {
        '_TXT': 'text',
        '_EVT': 'input',
    },

    'input': {
        '_TXT': 'value',
    },
    'textarea': {
        '_TXT': 'value',
    },
}


# customize tags in browser html
for tag in browser.html.tags:
    if tag != 'BODY':
        _customize_tag(tag)

# This tags has to be customized in advance
for x in ['txt', 'router-outlet']:
    _customize_tag(x, dotag=True)


# Override default tags with supercharged ones
__BRYTHON__.DOMNodeDict.tagsorig = __BRYTHON__.DOMNodeDict.tags
__BRYTHON__.DOMNodeDict.tags = tags

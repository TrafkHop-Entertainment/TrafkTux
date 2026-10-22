// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// vicinae_hotkey_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2026 Aurelien Brabant

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the "Software"),
    to deal in the Software without restriction, including without limitation
    the rights to use, copy, modify, merge, publish, distribute, sublicense,
    and/or sell copies of the Software, and to permit persons to whom the
    Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice (including the next
    paragraph) shall be included in all copies or substantial portions of the
    Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
    THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
    DEALINGS IN THE SOFTWARE.
  
*/

#pragma once

#include <functional>
#include <cstdint>
#include <string>
#include <wayland-server.h>

#define F std::function

struct wl_client;
struct wl_resource;

enum vicinaeHotkeyManagerV1Modifiers : uint32_t {
    VICINAE_HOTKEY_MANAGER_V1_MODIFIERS_SHIFT = 1,
    VICINAE_HOTKEY_MANAGER_V1_MODIFIERS_CTRL = 2,
    VICINAE_HOTKEY_MANAGER_V1_MODIFIERS_ALT = 4,
    VICINAE_HOTKEY_MANAGER_V1_MODIFIERS_SUPER = 8,
};

enum vicinaeHotkeyV1DenyReason : uint32_t {
    VICINAE_HOTKEY_V1_DENY_REASON_ALREADY_BOUND = 0,
    VICINAE_HOTKEY_V1_DENY_REASON_NOT_PERMITTED = 1,
    VICINAE_HOTKEY_V1_DENY_REASON_INVALID = 2,
};

enum vicinaeHotkeyV1RevokeReason : uint32_t {
    VICINAE_HOTKEY_V1_REVOKE_REASON_REMOVED = 0,
    VICINAE_HOTKEY_V1_REVOKE_REASON_SUPERSEDED = 1,
    VICINAE_HOTKEY_V1_REVOKE_REASON_NOT_PERMITTED = 2,
};


class CVicinaeHotkeyManagerV1;
class CVicinaeHotkeyV1;
class CWlSeat;
class CVicinaeHotkeyV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface vicinae_hotkey_manager_v1_interface;
extern const wl_interface vicinae_hotkey_v1_interface;

#endif

struct CVicinaeHotkeyManagerV1DestroyWrapper {
    wl_listener listener;
    CVicinaeHotkeyManagerV1* parent = nullptr;
};
            

class CVicinaeHotkeyManagerV1 {
  public:
    CVicinaeHotkeyManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CVicinaeHotkeyManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CVicinaeHotkeyManagerV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CVicinaeHotkeyManagerV1*)> &&handler);
    void setBind(F<void(CVicinaeHotkeyManagerV1*, uint32_t, uint32_t, vicinaeHotkeyManagerV1Modifiers, wl_resource*, const char*, const char*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CVicinaeHotkeyManagerV1*)> destroy;
        F<void(CVicinaeHotkeyManagerV1*, uint32_t, uint32_t, vicinaeHotkeyManagerV1Modifiers, wl_resource*, const char*, const char*)> bind;
    } requests;

    void onDestroyCalled();

    F<void(CVicinaeHotkeyManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CVicinaeHotkeyManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CVicinaeHotkeyV1DestroyWrapper {
    wl_listener listener;
    CVicinaeHotkeyV1* parent = nullptr;
};
            

class CVicinaeHotkeyV1 {
  public:
    CVicinaeHotkeyV1(wl_client* client, uint32_t version, uint32_t id);
    ~CVicinaeHotkeyV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CVicinaeHotkeyV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CVicinaeHotkeyV1*)> &&handler);

    // --------------- Events --------------- //

    void sendBound();
    void sendDenied(vicinaeHotkeyV1DenyReason, const char*);
    void sendRevoked(vicinaeHotkeyV1RevokeReason, const char*);
    void sendPressed(uint32_t, uint32_t);
    void sendReleased(uint32_t, uint32_t);
    void sendBoundRaw();
    void sendDeniedRaw(vicinaeHotkeyV1DenyReason, const char*);
    void sendRevokedRaw(vicinaeHotkeyV1RevokeReason, const char*);
    void sendPressedRaw(uint32_t, uint32_t);
    void sendReleasedRaw(uint32_t, uint32_t);

  private:
    struct {
        F<void(CVicinaeHotkeyV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CVicinaeHotkeyV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CVicinaeHotkeyV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F

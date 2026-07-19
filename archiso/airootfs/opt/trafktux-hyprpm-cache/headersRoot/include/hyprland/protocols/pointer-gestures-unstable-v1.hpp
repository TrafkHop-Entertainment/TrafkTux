// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// pointer_gestures_unstable_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2015, 2021 Red Hat Inc.

    Permission to use, copy, modify, distribute, and sell this
    software and its documentation for any purpose is hereby granted
    without fee, provided that the above copyright notice appear in
    all copies and that both that copyright notice and this permission
    notice appear in supporting documentation, and that the name of
    the copyright holders not be used in advertising or publicity
    pertaining to distribution of the software without specific,
    written prior permission.  The copyright holders make no
    representations about the suitability of this software for any
    purpose.  It is provided "as is" without express or implied
    warranty.

    THE COPYRIGHT HOLDERS DISCLAIM ALL WARRANTIES WITH REGARD TO THIS
    SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
    FITNESS, IN NO EVENT SHALL THE COPYRIGHT HOLDERS BE LIABLE FOR ANY
    SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
    WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN
    AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
    ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
    THIS SOFTWARE.
  
*/

#pragma once

#include <functional>
#include <cstdint>
#include <string>
#include <wayland-server.h>

#define F std::function

struct wl_client;
struct wl_resource;


class CZwpPointerGesturesV1;
class CZwpPointerGestureSwipeV1;
class CWlPointer;
class CZwpPointerGesturePinchV1;
class CWlPointer;
class CZwpPointerGestureHoldV1;
class CWlPointer;
class CZwpPointerGestureSwipeV1;
class CWlSurface;
class CZwpPointerGesturePinchV1;
class CWlSurface;
class CZwpPointerGestureHoldV1;
class CWlSurface;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface zwp_pointer_gestures_v1_interface;
extern const wl_interface zwp_pointer_gesture_swipe_v1_interface;
extern const wl_interface zwp_pointer_gesture_pinch_v1_interface;
extern const wl_interface zwp_pointer_gesture_hold_v1_interface;

#endif

struct CZwpPointerGesturesV1DestroyWrapper {
    wl_listener listener;
    CZwpPointerGesturesV1* parent = nullptr;
};
            

class CZwpPointerGesturesV1 {
  public:
    CZwpPointerGesturesV1(wl_client* client, uint32_t version, uint32_t id);
    ~CZwpPointerGesturesV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CZwpPointerGesturesV1*)> &&handler) {
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

    void setGetSwipeGesture(F<void(CZwpPointerGesturesV1*, uint32_t, wl_resource*)> &&handler);
    void setGetPinchGesture(F<void(CZwpPointerGesturesV1*, uint32_t, wl_resource*)> &&handler);
    void setRelease(F<void(CZwpPointerGesturesV1*)> &&handler);
    void setGetHoldGesture(F<void(CZwpPointerGesturesV1*, uint32_t, wl_resource*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CZwpPointerGesturesV1*, uint32_t, wl_resource*)> getSwipeGesture;
        F<void(CZwpPointerGesturesV1*, uint32_t, wl_resource*)> getPinchGesture;
        F<void(CZwpPointerGesturesV1*)> release;
        F<void(CZwpPointerGesturesV1*, uint32_t, wl_resource*)> getHoldGesture;
    } requests;

    void onDestroyCalled();

    F<void(CZwpPointerGesturesV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CZwpPointerGesturesV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CZwpPointerGestureSwipeV1DestroyWrapper {
    wl_listener listener;
    CZwpPointerGestureSwipeV1* parent = nullptr;
};
            

class CZwpPointerGestureSwipeV1 {
  public:
    CZwpPointerGestureSwipeV1(wl_client* client, uint32_t version, uint32_t id);
    ~CZwpPointerGestureSwipeV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CZwpPointerGestureSwipeV1*)> &&handler) {
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

    void setDestroy(F<void(CZwpPointerGestureSwipeV1*)> &&handler);

    // --------------- Events --------------- //

    void sendBegin(uint32_t, uint32_t, wl_resource*, uint32_t);
    void sendUpdate(uint32_t, wl_fixed_t, wl_fixed_t);
    void sendEnd(uint32_t, uint32_t, int32_t);
    void sendBeginRaw(uint32_t, uint32_t, wl_resource*, uint32_t);
    void sendUpdateRaw(uint32_t, wl_fixed_t, wl_fixed_t);
    void sendEndRaw(uint32_t, uint32_t, int32_t);

  private:
    struct {
        F<void(CZwpPointerGestureSwipeV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CZwpPointerGestureSwipeV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CZwpPointerGestureSwipeV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CZwpPointerGesturePinchV1DestroyWrapper {
    wl_listener listener;
    CZwpPointerGesturePinchV1* parent = nullptr;
};
            

class CZwpPointerGesturePinchV1 {
  public:
    CZwpPointerGesturePinchV1(wl_client* client, uint32_t version, uint32_t id);
    ~CZwpPointerGesturePinchV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CZwpPointerGesturePinchV1*)> &&handler) {
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

    void setDestroy(F<void(CZwpPointerGesturePinchV1*)> &&handler);

    // --------------- Events --------------- //

    void sendBegin(uint32_t, uint32_t, wl_resource*, uint32_t);
    void sendUpdate(uint32_t, wl_fixed_t, wl_fixed_t, wl_fixed_t, wl_fixed_t);
    void sendEnd(uint32_t, uint32_t, int32_t);
    void sendBeginRaw(uint32_t, uint32_t, wl_resource*, uint32_t);
    void sendUpdateRaw(uint32_t, wl_fixed_t, wl_fixed_t, wl_fixed_t, wl_fixed_t);
    void sendEndRaw(uint32_t, uint32_t, int32_t);

  private:
    struct {
        F<void(CZwpPointerGesturePinchV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CZwpPointerGesturePinchV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CZwpPointerGesturePinchV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CZwpPointerGestureHoldV1DestroyWrapper {
    wl_listener listener;
    CZwpPointerGestureHoldV1* parent = nullptr;
};
            

class CZwpPointerGestureHoldV1 {
  public:
    CZwpPointerGestureHoldV1(wl_client* client, uint32_t version, uint32_t id);
    ~CZwpPointerGestureHoldV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CZwpPointerGestureHoldV1*)> &&handler) {
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

    void setDestroy(F<void(CZwpPointerGestureHoldV1*)> &&handler);

    // --------------- Events --------------- //

    void sendBegin(uint32_t, uint32_t, wl_resource*, uint32_t);
    void sendEnd(uint32_t, uint32_t, int32_t);
    void sendBeginRaw(uint32_t, uint32_t, wl_resource*, uint32_t);
    void sendEndRaw(uint32_t, uint32_t, int32_t);

  private:
    struct {
        F<void(CZwpPointerGestureHoldV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CZwpPointerGestureHoldV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CZwpPointerGestureHoldV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F

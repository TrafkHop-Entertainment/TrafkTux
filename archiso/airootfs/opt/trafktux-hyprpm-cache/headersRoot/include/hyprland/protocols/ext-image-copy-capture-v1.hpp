// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// ext_image_copy_capture_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2021-2023 Andri Yngvason
    Copyright © 2024 Simon Ser

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
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
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

enum extImageCopyCaptureManagerV1Error : uint32_t {
    EXT_IMAGE_COPY_CAPTURE_MANAGER_V1_ERROR_INVALID_OPTION = 1,
};

enum extImageCopyCaptureManagerV1Options : uint32_t {
    EXT_IMAGE_COPY_CAPTURE_MANAGER_V1_OPTIONS_PAINT_CURSORS = 1,
};

enum extImageCopyCaptureSessionV1Error : uint32_t {
    EXT_IMAGE_COPY_CAPTURE_SESSION_V1_ERROR_DUPLICATE_FRAME = 1,
};

enum extImageCopyCaptureFrameV1Error : uint32_t {
    EXT_IMAGE_COPY_CAPTURE_FRAME_V1_ERROR_NO_BUFFER = 1,
    EXT_IMAGE_COPY_CAPTURE_FRAME_V1_ERROR_INVALID_BUFFER_DAMAGE = 2,
    EXT_IMAGE_COPY_CAPTURE_FRAME_V1_ERROR_ALREADY_CAPTURED = 3,
};

enum extImageCopyCaptureFrameV1FailureReason : uint32_t {
    EXT_IMAGE_COPY_CAPTURE_FRAME_V1_FAILURE_REASON_UNKNOWN = 0,
    EXT_IMAGE_COPY_CAPTURE_FRAME_V1_FAILURE_REASON_BUFFER_CONSTRAINTS = 1,
    EXT_IMAGE_COPY_CAPTURE_FRAME_V1_FAILURE_REASON_STOPPED = 2,
};

enum extImageCopyCaptureCursorSessionV1Error : uint32_t {
    EXT_IMAGE_COPY_CAPTURE_CURSOR_SESSION_V1_ERROR_DUPLICATE_SESSION = 1,
};


class CExtImageCopyCaptureManagerV1;
class CExtImageCopyCaptureSessionV1;
class CExtImageCaptureSourceV1;
class CExtImageCopyCaptureCursorSessionV1;
class CExtImageCaptureSourceV1;
class CWlPointer;
class CExtImageCopyCaptureSessionV1;
class CExtImageCopyCaptureFrameV1;
class CExtImageCopyCaptureFrameV1;
class CWlBuffer;
class CExtImageCopyCaptureCursorSessionV1;
class CExtImageCopyCaptureSessionV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface ext_image_copy_capture_manager_v1_interface;
extern const wl_interface ext_image_copy_capture_session_v1_interface;
extern const wl_interface ext_image_copy_capture_frame_v1_interface;
extern const wl_interface ext_image_copy_capture_cursor_session_v1_interface;

#endif

struct CExtImageCopyCaptureManagerV1DestroyWrapper {
    wl_listener listener;
    CExtImageCopyCaptureManagerV1* parent = nullptr;
};
            

class CExtImageCopyCaptureManagerV1 {
  public:
    CExtImageCopyCaptureManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtImageCopyCaptureManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtImageCopyCaptureManagerV1*)> &&handler) {
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

    void setCreateSession(F<void(CExtImageCopyCaptureManagerV1*, uint32_t, wl_resource*, extImageCopyCaptureManagerV1Options)> &&handler);
    void setCreatePointerCursorSession(F<void(CExtImageCopyCaptureManagerV1*, uint32_t, wl_resource*, wl_resource*)> &&handler);
    void setDestroy(F<void(CExtImageCopyCaptureManagerV1*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CExtImageCopyCaptureManagerV1*, uint32_t, wl_resource*, extImageCopyCaptureManagerV1Options)> createSession;
        F<void(CExtImageCopyCaptureManagerV1*, uint32_t, wl_resource*, wl_resource*)> createPointerCursorSession;
        F<void(CExtImageCopyCaptureManagerV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CExtImageCopyCaptureManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtImageCopyCaptureManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtImageCopyCaptureSessionV1DestroyWrapper {
    wl_listener listener;
    CExtImageCopyCaptureSessionV1* parent = nullptr;
};
            

class CExtImageCopyCaptureSessionV1 {
  public:
    CExtImageCopyCaptureSessionV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtImageCopyCaptureSessionV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtImageCopyCaptureSessionV1*)> &&handler) {
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

    void setCreateFrame(F<void(CExtImageCopyCaptureSessionV1*, uint32_t)> &&handler);
    void setDestroy(F<void(CExtImageCopyCaptureSessionV1*)> &&handler);

    // --------------- Events --------------- //

    void sendBufferSize(uint32_t, uint32_t);
    void sendShmFormat(uint32_t);
    void sendDmabufDevice(wl_array*);
    void sendDmabufFormat(uint32_t, wl_array*);
    void sendDone();
    void sendStopped();
    void sendBufferSizeRaw(uint32_t, uint32_t);
    void sendShmFormatRaw(uint32_t);
    void sendDmabufDeviceRaw(wl_array*);
    void sendDmabufFormatRaw(uint32_t, wl_array*);
    void sendDoneRaw();
    void sendStoppedRaw();

  private:
    struct {
        F<void(CExtImageCopyCaptureSessionV1*, uint32_t)> createFrame;
        F<void(CExtImageCopyCaptureSessionV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CExtImageCopyCaptureSessionV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtImageCopyCaptureSessionV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtImageCopyCaptureFrameV1DestroyWrapper {
    wl_listener listener;
    CExtImageCopyCaptureFrameV1* parent = nullptr;
};
            

class CExtImageCopyCaptureFrameV1 {
  public:
    CExtImageCopyCaptureFrameV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtImageCopyCaptureFrameV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtImageCopyCaptureFrameV1*)> &&handler) {
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

    void setDestroy(F<void(CExtImageCopyCaptureFrameV1*)> &&handler);
    void setAttachBuffer(F<void(CExtImageCopyCaptureFrameV1*, wl_resource*)> &&handler);
    void setDamageBuffer(F<void(CExtImageCopyCaptureFrameV1*, int32_t, int32_t, int32_t, int32_t)> &&handler);
    void setCapture(F<void(CExtImageCopyCaptureFrameV1*)> &&handler);

    // --------------- Events --------------- //

    void sendTransform(uint32_t);
    void sendDamage(int32_t, int32_t, int32_t, int32_t);
    void sendPresentationTime(uint32_t, uint32_t, uint32_t);
    void sendReady();
    void sendFailed(extImageCopyCaptureFrameV1FailureReason);
    void sendTransformRaw(uint32_t);
    void sendDamageRaw(int32_t, int32_t, int32_t, int32_t);
    void sendPresentationTimeRaw(uint32_t, uint32_t, uint32_t);
    void sendReadyRaw();
    void sendFailedRaw(extImageCopyCaptureFrameV1FailureReason);

  private:
    struct {
        F<void(CExtImageCopyCaptureFrameV1*)> destroy;
        F<void(CExtImageCopyCaptureFrameV1*, wl_resource*)> attachBuffer;
        F<void(CExtImageCopyCaptureFrameV1*, int32_t, int32_t, int32_t, int32_t)> damageBuffer;
        F<void(CExtImageCopyCaptureFrameV1*)> capture;
    } requests;

    void onDestroyCalled();

    F<void(CExtImageCopyCaptureFrameV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtImageCopyCaptureFrameV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtImageCopyCaptureCursorSessionV1DestroyWrapper {
    wl_listener listener;
    CExtImageCopyCaptureCursorSessionV1* parent = nullptr;
};
            

class CExtImageCopyCaptureCursorSessionV1 {
  public:
    CExtImageCopyCaptureCursorSessionV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtImageCopyCaptureCursorSessionV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtImageCopyCaptureCursorSessionV1*)> &&handler) {
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

    void setDestroy(F<void(CExtImageCopyCaptureCursorSessionV1*)> &&handler);
    void setGetCaptureSession(F<void(CExtImageCopyCaptureCursorSessionV1*, uint32_t)> &&handler);

    // --------------- Events --------------- //

    void sendEnter();
    void sendLeave();
    void sendPosition(int32_t, int32_t);
    void sendHotspot(int32_t, int32_t);
    void sendEnterRaw();
    void sendLeaveRaw();
    void sendPositionRaw(int32_t, int32_t);
    void sendHotspotRaw(int32_t, int32_t);

  private:
    struct {
        F<void(CExtImageCopyCaptureCursorSessionV1*)> destroy;
        F<void(CExtImageCopyCaptureCursorSessionV1*, uint32_t)> getCaptureSession;
    } requests;

    void onDestroyCalled();

    F<void(CExtImageCopyCaptureCursorSessionV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtImageCopyCaptureCursorSessionV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F

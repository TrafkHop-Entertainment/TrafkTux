// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// content_type_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2021 Emmanuel Gil Peyrot
    Copyright © 2022 Xaver Hugl

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

enum wpContentTypeManagerV1Error : uint32_t {
    WP_CONTENT_TYPE_MANAGER_V1_ERROR_ALREADY_CONSTRUCTED = 0,
};

enum wpContentTypeV1Type : uint32_t {
    WP_CONTENT_TYPE_V1_TYPE_NONE = 0,
    WP_CONTENT_TYPE_V1_TYPE_PHOTO = 1,
    WP_CONTENT_TYPE_V1_TYPE_VIDEO = 2,
    WP_CONTENT_TYPE_V1_TYPE_GAME = 3,
};


class CWpContentTypeManagerV1;
class CWpContentTypeV1;
class CWlSurface;
class CWpContentTypeV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface wp_content_type_manager_v1_interface;
extern const wl_interface wp_content_type_v1_interface;

#endif

struct CWpContentTypeManagerV1DestroyWrapper {
    wl_listener listener;
    CWpContentTypeManagerV1* parent = nullptr;
};
            

class CWpContentTypeManagerV1 {
  public:
    CWpContentTypeManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpContentTypeManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpContentTypeManagerV1*)> &&handler) {
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

    void setDestroy(F<void(CWpContentTypeManagerV1*)> &&handler);
    void setGetSurfaceContentType(F<void(CWpContentTypeManagerV1*, uint32_t, wl_resource*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CWpContentTypeManagerV1*)> destroy;
        F<void(CWpContentTypeManagerV1*, uint32_t, wl_resource*)> getSurfaceContentType;
    } requests;

    void onDestroyCalled();

    F<void(CWpContentTypeManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpContentTypeManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpContentTypeV1DestroyWrapper {
    wl_listener listener;
    CWpContentTypeV1* parent = nullptr;
};
            

class CWpContentTypeV1 {
  public:
    CWpContentTypeV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpContentTypeV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpContentTypeV1*)> &&handler) {
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

    void setDestroy(F<void(CWpContentTypeV1*)> &&handler);
    void setSetContentType(F<void(CWpContentTypeV1*, wpContentTypeV1Type)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CWpContentTypeV1*)> destroy;
        F<void(CWpContentTypeV1*, wpContentTypeV1Type)> setContentType;
    } requests;

    void onDestroyCalled();

    F<void(CWpContentTypeV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpContentTypeV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F

// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// ext_data_control_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2018 Simon Ser
    Copyright © 2019 Ivan Molodetskikh
    Copyright © 2024 Neal Gompa

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

enum extDataControlDeviceV1Error : uint32_t {
    EXT_DATA_CONTROL_DEVICE_V1_ERROR_USED_SOURCE = 1,
};

enum extDataControlSourceV1Error : uint32_t {
    EXT_DATA_CONTROL_SOURCE_V1_ERROR_INVALID_OFFER = 1,
};


class CExtDataControlManagerV1;
class CExtDataControlSourceV1;
class CExtDataControlDeviceV1;
class CWlSeat;
class CExtDataControlDeviceV1;
class CExtDataControlSourceV1;
class CExtDataControlSourceV1;
class CExtDataControlOfferV1;
class CExtDataControlOfferV1;
class CExtDataControlOfferV1;
class CExtDataControlSourceV1;
class CExtDataControlOfferV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface ext_data_control_manager_v1_interface;
extern const wl_interface ext_data_control_device_v1_interface;
extern const wl_interface ext_data_control_source_v1_interface;
extern const wl_interface ext_data_control_offer_v1_interface;

#endif

struct CExtDataControlManagerV1DestroyWrapper {
    wl_listener listener;
    CExtDataControlManagerV1* parent = nullptr;
};
            

class CExtDataControlManagerV1 {
  public:
    CExtDataControlManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtDataControlManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtDataControlManagerV1*)> &&handler) {
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

    void setCreateDataSource(F<void(CExtDataControlManagerV1*, uint32_t)> &&handler);
    void setGetDataDevice(F<void(CExtDataControlManagerV1*, uint32_t, wl_resource*)> &&handler);
    void setDestroy(F<void(CExtDataControlManagerV1*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CExtDataControlManagerV1*, uint32_t)> createDataSource;
        F<void(CExtDataControlManagerV1*, uint32_t, wl_resource*)> getDataDevice;
        F<void(CExtDataControlManagerV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CExtDataControlManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtDataControlManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtDataControlDeviceV1DestroyWrapper {
    wl_listener listener;
    CExtDataControlDeviceV1* parent = nullptr;
};
            

class CExtDataControlDeviceV1 {
  public:
    CExtDataControlDeviceV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtDataControlDeviceV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtDataControlDeviceV1*)> &&handler) {
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

    void setSetSelection(F<void(CExtDataControlDeviceV1*, wl_resource*)> &&handler);
    void setDestroy(F<void(CExtDataControlDeviceV1*)> &&handler);
    void setSetPrimarySelection(F<void(CExtDataControlDeviceV1*, wl_resource*)> &&handler);

    // --------------- Events --------------- //

    void sendDataOffer(CExtDataControlOfferV1*);
    void sendSelection(CExtDataControlOfferV1*);
    void sendFinished();
    void sendPrimarySelection(CExtDataControlOfferV1*);
    void sendDataOfferRaw(CExtDataControlOfferV1*);
    void sendSelectionRaw(wl_resource*);
    void sendFinishedRaw();
    void sendPrimarySelectionRaw(wl_resource*);

  private:
    struct {
        F<void(CExtDataControlDeviceV1*, wl_resource*)> setSelection;
        F<void(CExtDataControlDeviceV1*)> destroy;
        F<void(CExtDataControlDeviceV1*, wl_resource*)> setPrimarySelection;
    } requests;

    void onDestroyCalled();

    F<void(CExtDataControlDeviceV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtDataControlDeviceV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtDataControlSourceV1DestroyWrapper {
    wl_listener listener;
    CExtDataControlSourceV1* parent = nullptr;
};
            

class CExtDataControlSourceV1 {
  public:
    CExtDataControlSourceV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtDataControlSourceV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtDataControlSourceV1*)> &&handler) {
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

    void setOffer(F<void(CExtDataControlSourceV1*, const char*)> &&handler);
    void setDestroy(F<void(CExtDataControlSourceV1*)> &&handler);

    // --------------- Events --------------- //

    void sendSend(const char*, int32_t);
    void sendCancelled();
    void sendSendRaw(const char*, int32_t);
    void sendCancelledRaw();

  private:
    struct {
        F<void(CExtDataControlSourceV1*, const char*)> offer;
        F<void(CExtDataControlSourceV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CExtDataControlSourceV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtDataControlSourceV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtDataControlOfferV1DestroyWrapper {
    wl_listener listener;
    CExtDataControlOfferV1* parent = nullptr;
};
            

class CExtDataControlOfferV1 {
  public:
    CExtDataControlOfferV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtDataControlOfferV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtDataControlOfferV1*)> &&handler) {
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

    void setReceive(F<void(CExtDataControlOfferV1*, const char*, int32_t)> &&handler);
    void setDestroy(F<void(CExtDataControlOfferV1*)> &&handler);

    // --------------- Events --------------- //

    void sendOffer(const char*);
    void sendOfferRaw(const char*);

  private:
    struct {
        F<void(CExtDataControlOfferV1*, const char*, int32_t)> receive;
        F<void(CExtDataControlOfferV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CExtDataControlOfferV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtDataControlOfferV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F

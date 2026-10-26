/* === This file is part of Calamares - <https://calamares.io> ===
 *
 *   SPDX-FileCopyrightText: 2015 Teo Mrnjavac <teo@kde.org>
 *   SPDX-FileCopyrightText: 2018 Adriaan de Groot <groot@kde.org>
 *   SPDX-License-Identifier: GPL-3.0-or-later
 *
 *   Calamares is Free Software: see the License-Identifier above.
 *
 */

import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation
{
    id: presentation

    function nextSlide() {
        console.log("QML Component (default slideshow) Next slide");
        presentation.goToNextSlide();
    }

    // Dauer pro Bild in ms, bevor automatisch zum naechsten gewechselt wird.
    // Vorher 1000 (= 1 Sekunde) - deutlich zu kurz, die Bilder sind quasi
    // "vorbeigeflitzt". 6 Bilder * 5000ms = 30s fuer einen kompletten
    // Durchlauf, danach beginnt onActivate() wieder bei Slide 0.
    Timer {
        id: advanceTimer
        interval: 5000
        running: presentation.activatedInCalamares
        repeat: true
        onTriggered: nextSlide()
    }

    // Jedes Image fuellt vorher mit width/height: 200 nur eine feste
    // 200x200px-Box in der Bildschirmmitte - bei einem 800x520px-Fenster
    // (siehe branding.desc windowSize) wirkt das winzig und skaliert auch
    // nicht mit der tatsaechlichen Fenstergroesse mit. anchors.fill: parent
    // laesst das Image stattdessen den kompletten Slide-Bereich einnehmen;
    // fillMode: Stretch fuellt diese Flaeche komplett aus, OHNE Ruecksicht
    // auf das Seitenverhaeltnis - anders als PreserveAspectFit (das Raender
    // links/rechts bzw. oben/unten laesst, falls Bild- und Fenster-
    // Seitenverhaeltnis nicht exakt uebereinstimmen) wird das Bild bei
    // Bedarf gestaucht/gestreckt, dafuer bleiben aber nie Raender stehen.
    Slide {

        Image {
            id: background1
            source: "TrafkHop.png"
            anchors.fill: parent
            fillMode: Image.Stretch
        }
    }
    Slide {

        Image {
            id: background2
            source: "sddm.png"
            anchors.fill: parent
            fillMode: Image.Stretch
        }
    }
    Slide {

        Image {
            id: background3
            source: "Desktop.png"
            anchors.fill: parent
            fillMode: Image.Stretch
        }
    }
    Slide {

        Image {
            id: background4
            source: "pyleyrun.png"
            anchors.fill: parent
            fillMode: Image.Stretch
        }
    }
    Slide {

        Image {
            id: background5
            source: "bgb.png"
            anchors.fill: parent
            fillMode: Image.Stretch
        }
    }
    Slide {

        Image {
            id: background6
            source: "bryce.png"
            anchors.fill: parent
            fillMode: Image.Stretch
        }
    }




    // When this slideshow is loaded as a V1 slideshow, only
    // activatedInCalamares is set, which starts the timer (see above).
    //
    // In V2, also the onActivate() and onLeave() methods are called.
    // These example functions log a message (and re-start the slides
    // from the first).
    function onActivate() {
        console.log("QML Component (default slideshow) activated");
        presentation.currentSlide = 0;
    }

    function onLeave() {
        console.log("QML Component (default slideshow) deactivated");
    }

}

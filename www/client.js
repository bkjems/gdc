var lastupdate = 0;
var dps = []; // dataPoints
var dps2 = []; // dataPoints

function getChart() {
    var chart2 = new CanvasJS.Chart("chartContainer", {
        animationEnabled: true,
        zoomEnabled: true,
        title: {
            fontColor: "rgba(76,76,76)",
            text: "Garage Temperatures"
        },
        axisY: {
            includeZero: false,
            valueFormatString: "#0.## F",
            stripLines: [{
                labelFontSize: 10,
                labelAlign: "near",
                value: 32,
                label: "32 F",
                labelFontColor: "blue",
                color: "blue"

            }]
        },
        axisX: {
            crosshair: {
                labelBackgroundColor: "#33558B",
                enabled: true
            },
            reversed: false,
            interval: 3,
            intervalType: "day",
            labelAutoFit: true,
            valueFormatString: "MMM DD",
            labelAngle: -45
        },
        toolTip: {
            shared: true
        },
        data: [{
                name: "Low/High Temperature",
                fillOpacity: .6,
                type: "rangeArea",
                showInLegend: true,
                indexLabelFontSize: 9,
                yValueFormatString: "#0.## F",
                xValueFormatString: "DD MMM YYYY",
                legendText: "High/Low",
                color: "rgba(0,135,147,.4)",
                markerType: "circle",
                dataPoints: dps
            },
            {
                name: "Avg Day Temperature",
                lineDashType: "dash",
                connectNullData: true,
                type: "spline",
                yValueFormatString: "#0.## °F",
                showInLegend: true,
                color: "orange",
                dataPoints: dps2
            }
        ]
    });
    return chart2;
};

function formatState(state, time) {
    dateStr = dateFormat(new Date(parseInt(time) * 1000), "mmm dS, h:MM TT");
    return state.charAt(0).toUpperCase() + state.slice(1) + " as of " + dateStr;
};

function click(name) {
    $.ajax({
        url: "clk",
        data: {
            'id': name
        }
    })
};

function clickGraph_shed() {
    $.ajax({
        url: "graphshed",
        dataType: 'json',
        success: function (data) {
            c = getChart();
            c.options.title.text = "Shed Temperatures";

            dps.length = 0
            data.forEach((item) => {
                dps.push({
                    x: new Date(item.yy, item.m - 1, item.d),
                    y: item.y
                });
            });

            dps2.length = 0
            data.forEach((item) => {
                dps2.push({
                    x: new Date(item.yy, item.m - 1, item.d),
                    y: item.avg_temp
                });
            });
            c.render();
        },
        error: function (data) {
            console.log(data);
        }
    })
}

function clickGraph() {
    $.ajax({
        url: "graph",
        dataType: 'json',
        success: function (data) {
            dps.length = 0
            data.forEach((item) => {
                dps.push({
                    x: new Date(item.yy, item.m - 1, item.d),
                    y: item.y
                });
            });

            dps2.length = 0
            data.forEach((item) => {
                dps2.push({
                    x: new Date(item.yy, item.m - 1, item.d),
                    y: item.avg_temp
                });
            });

            chart = getChart();
            chart.render()
            $("#log_message").html("");
        },
        error: function (data) {
            console.log(data);
        }
    })
};

function clickWeather() {
    $.ajax({
        url: "weather",
        beforeSend: function () {
            $("#log_message").html("");
            $("#spin").html("Loading...");
            $('#spin').show()
        },
        complete: function (response) {
            $('#spin').hide()
        },
        success: function (data) {
            $("#json").text(data);
            $("#chartContainer").html("");
        }
    })
};

function clickLogs() {
    $.ajax({
        url: "log",
        success: function (data) {
            $("#log_message").html(data);
            $("#chartContainer").html("");
        }
    })
};

function clickGetTemp() {
    $.ajax({
        url: "gettemp",
        beforeSend: function () {
            $("#log_message").html("");
            $("#spin").html("Loading...");
            $('#spin').show()
        },
        complete: function (response) {
            $('#spin').hide()
        },
        success: function (data) {
            $("#log_message").html(data);
            $("#chartContainer").html("");
            $("#json").text("");
        }
    })
};

function clickTemps() {
    $.ajax({
        url: "temps",
        success: function (data) {
            $("#log_message").html(data);
            $("#chartContainer").html("");
            $("#json").text("");
        }
    })
};

function clickMotionTest() {
    $.ajax({
        url: "mot",
        success: function (data) {
            $("#log_message").html(data);
            $("#chartContainer").html("");
        }
    })
};

function clickCloseAll() {
    $.ajax({
        url: "closeall",
        success: function (data) {
            $("#log_message").html(data);
            $("#chartContainer").html("");
            $("#json").text("");

        }
    })
};

function uptime() {
    $.ajax({
        url: "upt",
        success: function (data) {
            $("#uptime").html(data)
            setTimeout('uptime()', 60000)
        },
        error: function (XMLHttpRequest, textStatus, errorThrown) {
            setTimeout('uptime()', 60000)
        },
        dataType: "json",
        timeout: 60000
    });
}


function poll() {
    $.ajax({
        url: "upd",
        data: {
            'lastupdate': lastupdate
        },
        success: function (response, status) {
            lastupdate = response.timestamp;
            for (var i = 0; i < response.update.length; i++) {
                var id = response.update[i][0];
                var state = response.update[i][1];
                var time = response.update[i][2];
                $("#" + id + " p").html(formatState(state, time));
                $("#" + id + " img").attr("src", "img/" + state + ".png")
                $("#doorlist").listview('refresh');
            }
            setTimeout('poll()', 1000);
        },
        // handle error
        error: function (XMLHttpRequest, textStatus, errorThrown) {
            // try again in 10 seconds if there was a request error
            setTimeout('poll();', 10000);
        },
        //complete: poll,
        dataType: "json",
        timeout: 30000
    });
};

function init() {
    uptime()
    poll()
}

$.ajax({
    url: "cfg",
    success: function (data) {
        for (var i = 0; i < data.length; i++) {
            var id = data[i][0];
            var name = data[i][1];
            var state = data[i][2];
            var time = data[i][3];
            var li = '<li id="' + id + '" data-icon="false">';
            li = li + '<a href="javascript:click(\'' + id + '\');">';
            li = li + '<img src="img/' + state + '.png" />';
            li = li + '<h3>' + name + '</h3>';
            li = li + '<p>' + formatState(state, time) + '</p>';
            li = li + '</a></li>';
            $("#doorlist").append(li);
            $("#doorlist").listview('refresh');
        }
    }
});

$(document).live('pageinit', init);
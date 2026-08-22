var svgCanvas = null;

// when the editor is opened directly from the file system, the drawing is
// posted to the laser server running on localhost; otherwise stay same-origin
var LASER_SERVER = (location.protocol === 'file:') ? 'http://localhost:8000/' : '/';

var setColorIcon = function(id) {
    $('#color_white').removeClass('button_selected');
    $('#color_red').removeClass('button_selected');
    $('#color_green').removeClass('button_selected');
    $('#color_blue').removeClass('button_selected');
    $('#color_cyan').removeClass('button_selected');
    $('#color_magenta').removeClass('button_selected');
    $('#color_yellow').removeClass('button_selected');
    $(id).addClass('button_selected');
};

var setToolIcon = function(id) {
    $('#select').removeClass('button_selected');
    $('#path').removeClass('button_selected');
    $('#line').removeClass('button_selected');
    $('#rect').removeClass('button_selected');
    $('#ellipse').removeClass('button_selected');
    $(id).addClass('button_selected');
};

$(function(){

    svgCanvas = new SvgCanvas(document.getElementById("svgcanvas"));

    svgCanvas.setMode('fhpath');
    svgCanvas.setStrokeWidth(3);
    svgCanvas.setStrokeColor('#ff0000');
    svgCanvas.setFillColor('none');

    document.getElementById("toolarea").ondragstart = function() {return false;};

    $('#select').click(function(){ svgCanvas.setMode('select'); setToolIcon('#select'); });
    $('#path').click(function(){ svgCanvas.setMode('fhpath'); setToolIcon('#path'); });
    $('#line').click(function(){ svgCanvas.setMode('line'); setToolIcon('#line'); });
    $('#rect').click(function(){ svgCanvas.setMode('rect'); setToolIcon('#rect'); });
    $('#ellipse').click(function(){ svgCanvas.setMode('ellipse'); setToolIcon('#ellipse'); });

    $('#clear').click(function(){ svgCanvas.clear(); });
    $('#delete').click(function(){ svgCanvas.deleteSelectedElements(); });

    // display the current drawing on the laser
    $('#laser').click(function(){
        $.post(LASER_SERVER, {svg: svgCanvas.getSvgString()})
            .fail(function(){ alert('Could not reach the laser server at ' + LASER_SERVER); });
    });

    // export the current drawing as an svg file
    $('#export').click(function(){
        var blob = new Blob([svgCanvas.getSvgString()], {type: 'image/svg+xml'});
        var link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'drawing.svg';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
    });

    $('#color_white').click(function(){ svgCanvas.setStrokeColor('#ffffff'); setColorIcon('#color_white'); });
    $('#color_red').click(function(){ svgCanvas.setStrokeColor('#ff0000'); setColorIcon('#color_red'); });
    $('#color_green').click(function(){ svgCanvas.setStrokeColor('#00ff00'); setColorIcon('#color_green'); });
    $('#color_blue').click(function(){ svgCanvas.setStrokeColor('#0000ff'); setColorIcon('#color_blue'); });
    $('#color_cyan').click(function(){ svgCanvas.setStrokeColor('#00ffff'); setColorIcon('#color_cyan'); });
    $('#color_magenta').click(function(){ svgCanvas.setStrokeColor('#ff00ff'); setColorIcon('#color_magenta'); });
    $('#color_yellow').click(function(){ svgCanvas.setStrokeColor('#ffff00'); setColorIcon('#color_yellow'); });

    $('#template1').click(function(){ svgCanvas.insertTemplate(template1); });
    $('#template2').click(function(){ svgCanvas.insertTemplate(template2); });
    $('#template3').click(function(){ svgCanvas.insertTemplate(template3); });
    $('#template4').click(function(){ svgCanvas.insertTemplate(template4); });
    $('#template5').click(function(){ svgCanvas.insertTemplate(template5); });

});
